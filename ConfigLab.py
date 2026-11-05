"""
╔══════════════════════════════════════════════════════════════╗
║  ConfigLabs v2.0 — Multi-Vendor Network Config Generator    ║
║                                                              ║
║  Supported vendors:                                          ║
║    🟢 H3C Comware v7                                         ║
║    🔵 Cisco IOS (Catalyst 2960/3750, ISR)                   ║
║    🔵 Cisco IOS-XE (Catalyst 9000, modern ISR)              ║
║    🔵 Cisco NX-OS (Nexus switches)                          ║
║    🟣 Ruijie RGOS (switch, router, WLAN AC + fit AP)        ║
║                                                              ║
║  Coming soon: Huawei VRP, Juniper Junos, Arista EOS,        ║
║               MikroTik RouterOS                              ║
║                                                              ║
║  https://configlabs.online                                   ║
╚══════════════════════════════════════════════════════════════╝
"""
from flask import Flask, request, jsonify, redirect, url_for, g
from flask_cors import CORS
from authlib.integrations.flask_client import OAuth
from models import db, User, SavedFile, WifiProject, WifiPlan, TranslateUse, ProWaitlist
from datetime import datetime, timedelta
from functools import wraps
import jwt
import os
import json
import re
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB request cap
# Same-origin in production; allow the site itself and local dev only.
CORS(app, supports_credentials=True, origins=[
    'https://configlabs.online', 'https://www.configlabs.online',
    r'http://localhost:\d+', r'http://127\.0\.0\.1:\d+',
])

# ── Database ────────────────────────────────────────────────
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///configlabs.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
if _db_url.startswith('postgresql://'):
    _db_url = _db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
# Neon scales to zero -> reconnect cleanly after idle
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True, 'pool_recycle': 280}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
def _secret(env_name, label):
    """Return the configured secret. Never fall back to a value that is public in the repo:
    if the env var is missing, derive a private one from other server-side secrets (stable across
    instances), or as a last resort use a random per-process value (local dev)."""
    val = os.environ.get(env_name)
    if val:
        return val
    import hashlib, secrets as _sec
    base = os.environ.get('GOOGLE_CLIENT_SECRET') or os.environ.get('DATABASE_URL')
    print(f"[WARN] {env_name} is not set - set it in the environment (Vercel project settings).")
    if base:
        return hashlib.sha256((label + ':' + base).encode()).hexdigest()
    return _sec.token_hex(32)

app.config['SECRET_KEY'] = _secret('SESSION_SECRET', 'session')

db.init_app(app)

# ── OAuth ───────────────────────────────────────────────────
oauth = OAuth(app)

google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# ── JWT helpers ─────────────────────────────────────────────
JWT_SECRET  = _secret('JWT_SECRET', 'jwt')
JWT_EXPIRES = 60 * 60 * 24 * 30   # 30 days

def create_token(user):
    payload = {
        'user_id':    user.id,
        'email':      user.email,
        'name':       user.name,
        'avatar_url': user.avatar_url,
        'exp': datetime.utcnow() + timedelta(seconds=JWT_EXPIRES),
        'iat': datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def decode_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
    except Exception:
        return None

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        raw   = request.headers.get('Authorization', '')
        token = raw.replace('Bearer ', '').strip()
        data  = decode_token(token)
        if not data:
            return jsonify({'error': 'Unauthorized'}), 401
        g.current_user = data
        return f(*args, **kwargs)
    return wrapper

# ── Init DB on first request ────────────────────────────────
with_app_context_done = False

@app.before_request
def init_db_once():
    global with_app_context_done
    if not with_app_context_done:
        db.create_all()
        with_app_context_done = True

APP_NAME = "ConfigLabs"
APP_VERSION = "7.7.0"

# ==========================================================
# VENDOR / OS REGISTRY
# ==========================================================
VENDORS = {
    "h3c": {
        "name": "H3C",
        "status": "available",
        "color": "#7cf4c7",
        "os_list": [
            {"id": "comware", "name": "Comware v7", "desc": "Classic switches/routers", "status": "available"}
        ]
    },
    "cisco": {
        "name": "Cisco",
        "status": "available",
        "color": "#a8b5ff",
        "os_list": [
            {"id": "ios",   "name": "IOS",    "desc": "Classic (Catalyst 2960/3750, ISR)", "status": "available"},
            {"id": "iosxe", "name": "IOS-XE", "desc": "Modern (Catalyst 9000, ISR 4k)",    "status": "available"},
            {"id": "nxos",  "name": "NX-OS",  "desc": "Nexus data center",                 "status": "available"}
        ]
    },
    "ruijie": {
        "name": "Ruijie",
        "status": "available",
        "color": "#ff9aa8",
        "os_list": [
            {"id": "rgos_switch", "name": "RGOS Switch",    "desc": "RG-S series (L2/L3 access, core)",   "status": "available"},
            {"id": "rgos_router", "name": "RGOS Router",    "desc": "RSR / EG gateways (NAT, routing)",   "status": "available"},
            {"id": "rgos_wlan",   "name": "WLAN AC + AP",   "desc": "Wireless controller + fit APs",       "status": "available"}
        ]
    },
    "huawei":   {"name": "Huawei",   "status": "coming_soon", "os_list": [{"id": "vrp",   "name": "VRP",   "status": "coming_soon"}]},
    "juniper":  {"name": "Juniper",  "status": "coming_soon", "os_list": [{"id": "junos", "name": "Junos", "status": "coming_soon"}]},
    "arista":   {"name": "Arista",   "status": "coming_soon", "os_list": [{"id": "eos",   "name": "EOS",   "status": "coming_soon"}]},
    "mikrotik": {"name": "MikroTik", "status": "coming_soon", "os_list": [{"id": "routeros", "name": "RouterOS", "status": "coming_soon"}]}
}

# ==========================================================
# SHARED HELPERS
# ==========================================================
def cidr_to_mask(cidr):
    cidr = int(cidr)
    mask = (0xffffffff >> (32 - cidr)) << (32 - cidr)
    return ".".join([str((mask >> i) & 0xff) for i in [24, 16, 8, 0]])

def cidr_to_wildcard(cidr):
    cidr = int(cidr)
    mask = (0xffffffff >> (32 - cidr)) << (32 - cidr)
    wildcard = mask ^ 0xffffffff
    return ".".join([str((wildcard >> i) & 0xff) for i in [24, 16, 8, 0]])

def format_area(area):
    """Format OSPF area as 0.0.0.0 dotted"""
    area = str(area).strip()
    if not area: return "0.0.0.0"
    if "." in area: return area
    try:
        n = int(area)
        return f"{(n >> 24) & 0xff}.{(n >> 16) & 0xff}.{(n >> 8) & 0xff}.{n & 0xff}"
    except:
        return area

def normalize_vlan_list(vlans_str):
    """Normalize VLAN list: '10 20 30' → '10,20,30' (for Cisco)"""
    if not vlans_str: return ""
    # Convert spaces and 'to' ranges to comma-separated
    result = vlans_str.replace(",", " ").split()
    return ",".join(result)


def _pbr_ip(v, what, errs, cidr=False):
    import ipaddress
    try:
        if cidr:
            ipaddress.ip_interface(v)
        else:
            ipaddress.IPv4Address(v)
        return True
    except Exception:
        errs.append(f"{what}: '{v}' is not a valid IPv4 {'address/CIDR' if cidr else 'address'}")
        return False

def gen_comware_pbr(pbr):
    """Multi-ISP policy-based routing with NQA + Track failover (H3C Comware v7), up to 5 ISPs.
    mode 'failover': every rule prefers ISP1, then ISP2 ...
    mode 'mutual'  : rule n prefers ISP n (rotating); a rule may also pin its own 'primary' ISP (1..5)."""
    MAXISP = 5
    isps = [i for i in (pbr.get("isps") or []) if i.get("gateway")][:MAXISP]
    rules = [l for l in (pbr.get("lans") or []) if l.get("network") or l.get("dst_network")]
    if not isps: return []
    errs = []
    nq = pbr.get("nqa") or {}
    def num(v, d, lo, hi, what):
        if v in (None, ""): return d
        try:
            n = int(v)
            if lo <= n <= hi: return n
        except Exception: pass
        errs.append(f"{what}: must be a number between {lo} and {hi}")
        return d
    freq   = num(nq.get("frequency"), 3000, 1000, 604800000, "NQA frequency (ms)")
    count  = num(nq.get("probe_count"), 0, 0, 15, "NQA probe count")
    tmo    = num(nq.get("probe_timeout"), 0, 10, 3600000, "NQA probe timeout (ms)")
    thr    = num(nq.get("threshold"), 3, 1, 100, "NQA failure threshold")
    src    = (nq.get("source_ip") or "").strip()
    if src: _pbr_ip(src, "NQA source IP", errs)
    defaults = ['8.8.8.8', '1.1.1.1', '9.9.9.9', '208.67.222.222', '8.8.4.4']
    for n, isp in enumerate(isps, 1):
        _pbr_ip(isp["gateway"], f"ISP {n} gateway", errs)
        if isp.get("probe_ip"): _pbr_ip(isp["probe_ip"], f"ISP {n} probe target", errs)
        if isp.get("wan_ip"): _pbr_ip(isp["wan_ip"], f"ISP {n} WAN IP", errs, cidr=True)
    for k, l in enumerate(rules, 1):
        for key, lab in (("network", "source"), ("dst_network", "destination")):
            if l.get(key):
                if _pbr_ip(l[key], f"Rule {k} {lab} network", errs):
                    try:
                        if not (0 <= int(l.get("cidr" if key == "network" else "dst_cidr", 32)) <= 32): raise ValueError
                    except Exception:
                        errs.append(f"Rule {k} {lab} CIDR must be 0-32")
        if l.get("dst_port"):
            try:
                if not (1 <= int(l["dst_port"]) <= 65535): raise ValueError
            except Exception:
                errs.append(f"Rule {k} destination port must be 1-65535")
        if l.get("primary") not in (None, ""):
            try:
                if not (1 <= int(l["primary"]) <= len(isps)): raise ValueError
            except Exception:
                errs.append(f"Rule {k} primary ISP must be 1-{len(isps)}")
    if errs:
        raise ValueError("PBR input error - " + "; ".join(errs[:6]))

    out = ["# --- Multi-ISP PBR (NQA + Track) ---", "#"]
    for n, isp in enumerate(isps, 1):
        tag = "isp" + chr(64 + n)
        out += [f"nqa entry admin {tag}", " type icmp-echo",
                f" destination ip {isp.get('probe_ip') or defaults[n-1]}",
                f" next-hop ip {isp['gateway']}", f" frequency {freq}"]
        if count: out.append(f" probe count {count}")
        if tmo:   out.append(f" probe timeout {tmo}")
        if src:   out.append(f" source ip {src}")
        out += [f" reaction 1 checked-element probe-fail threshold-type consecutive {thr} action-type trigger-only",
                f"nqa schedule admin {tag} start-time now lifetime forever",
                f"track {n} nqa entry admin {tag} reaction 1", "#"]
    for n, isp in enumerate(isps, 1):
        wi = isp.get("wan_interface")
        if not wi: continue
        out.append(f"interface {wi}")
        out.append(f" description {isp.get('name') or 'ISP-' + chr(64+n)}")
        if isp.get("wan_ip"):
            a, m = isp["wan_ip"].split("/")
            out.append(f" ip address {a} {cidr_to_mask(m)}")
        if isp.get("nat", True): out.append(" nat outbound")
        out.append("#")
    for n, isp in enumerate(isps, 1):
        line = f"ip route-static 0.0.0.0 0 {isp['gateway']} track {n}"
        if n > 1: line += f" preference {50 + n * 10}"
        out.append(line)
    out.append("#")
    if rules:
        pname = pbr.get("policy_name") or "PBR-ISP"
        base = int(pbr.get("acl_base") or 3100)
        mutual = pbr.get("mode") == "mutual"
        for k, l in enumerate(rules):
            rid = f" description {l.get('name') or 'RULE' + str(k+1)}"
            proto = l.get("protocol") or "ip"
            line = f" rule 5 permit {proto}"
            if l.get("network"):
                line += f" source {l['network']} {cidr_to_wildcard(l.get('cidr') or 32)}"
            if l.get("dst_network"):
                line += f" destination {l['dst_network']} {cidr_to_wildcard(l.get('dst_cidr') or 32)}"
            if l.get("dst_port") and proto in ("tcp", "udp"):
                line += f" destination-port eq {l['dst_port']}"
            out += [f"acl advanced {base + k}", rid, line, "#"]
        for k, l in enumerate(rules):
            if l.get("primary") not in (None, ""):
                first = int(l["primary"]) - 1
            else:
                first = (k % len(isps)) if mutual else 0
            order = [(first + j) % len(isps) + 1 for j in range(len(isps))]
            out.append(f"policy-based-route {pname} permit node {(k + 1) * 10}")
            out.append(f" if-match acl {base + k}")
            for n in order:
                out.append(f" apply next-hop {isps[n-1]['gateway']} track {n}")
            out.append("#")
        done = set()
        for l in rules:
            it = l.get("interface")
            if it and it not in done:
                done.add(it)
                out += [f"interface {it}", f" ip policy-based-route {pname}", "#"]
    return out

# ============================================================
# H3C COMWARE v7 GENERATOR
# ============================================================
def _h3c_vl(v):
    """'10 20 30-40' / '10,20,30-40' -> '10 20 30 to 40' (Comware range syntax)"""
    import re as _re
    t = " ".join(str(v).replace(",", " ").split())
    return _re.sub(r"(\d+)\s*-\s*(\d+)", r"\1 to \2", t)

def _h3c_vl_lines(v, per_line=10):
    """VLAN list -> Comware chunks of at most 10 items (a VLAN or an 'a to b' range) per command.
    Accepts '2 8 25 to 26', '2,8,25-26' ...; sorts, dedupes and merges consecutive VLANs.
    Anything that is not a valid VLAN list is passed through unchanged as a single chunk."""
    import re as _re
    t = _re.sub(r"\s*(?:-|\bto\b)\s*", "-", str(v).replace(",", " "), flags=_re.I).split()
    ids = set()
    for tok in t:
        m = _re.fullmatch(r"(\d+)(?:-(\d+))?", tok)
        if not m: return [_h3c_vl(v)] if str(v).strip() else []
        a = int(m.group(1)); b = int(m.group(2) or a)
        if a > b: a, b = b, a
        if a < 1 or b > 4094: return [_h3c_vl(v)]
        ids.update(range(a, b + 1))
    items, s = [], sorted(ids)
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[j] + 1: j += 1
        items.append(str(s[i]) if i == j else f"{s[i]} to {s[j]}")
        i = j + 1
    return [" ".join(items[k:k + per_line]) for k in range(0, len(items), per_line)]

def _h3c_pf(o):
    r = []
    for key, d in (("acl_in", "inbound"), ("acl_out", "outbound")):
        v = _rj_s(o.get(key))
        if v: r.append(f" packet-filter {v} {d}" if v.isdigit() else f" packet-filter name {v} {d}")
    return r

def _h3c_vrrp(o):
    items = o.get("vrrp")
    if not isinstance(items, list):
        items = [{"id": o.get("vrrp_id"), "ip": o.get("vrrp_ip"), "priority": o.get("vrrp_prio")}] if o.get("vrrp_id") else []
    r = []
    for v in items:
        if not isinstance(v, dict) or not (v.get("id") and v.get("ip")): continue
        r.append(f" vrrp vrid {_rj_s(v['id'])} virtual-ip {_rj_s(v['ip'])}")
        if v.get("priority"): r.append(f" vrrp vrid {_rj_s(v['id'])} priority {_rj_s(v['priority'])}")
    return r

def _h3c_system_extras(sd):
    """STP, local user + SSH, SNMP and syslog for the H3C generator (used by the translator)."""
    c = []
    if sd.get("stp_mode") in ("rstp", "mstp", "pvst"):
        c += [f"stp mode {sd['stp_mode']}", "stp global enable", "#"]
    if sd.get("bpdu_guard"): c += ["stp bpdu-protection", "#"]
    user, pw = _rj_s(sd.get("admin_user")), _rj_s(sd.get("admin_pass"))
    if sd.get("ssh") or user:
        c.append("ssh server enable")
        c.append("# once per device, run from user view: public-key local create rsa")
        c += ["line vty 0 4", " authentication-mode scheme", " protocol inbound ssh", "#"]
    if user:
        c += [f"local-user {user} class manage"]
        if pw: c.append(f" password simple {pw}")
        c += [" service-type ssh terminal", " authorization-attribute user-role network-admin", "#"]
    comms = sd.get("snmp_communities")
    if not isinstance(comms, list):
        comms = [{"name": sd["snmp_community"], "mode": "read"}] if sd.get("snmp_community") else []
    hosts = sd.get("snmp_hosts")
    if not isinstance(hosts, list):
        hosts = [{"ip": sd["snmp_host"], "community": (comms[0]["name"] if comms else "public")}] if sd.get("snmp_host") else []
    if comms or hosts:
        c += ["snmp-agent", "snmp-agent sys-info version v2c"]
        for cm in comms:
            if isinstance(cm, dict) and cm.get("name"):
                c.append(f"snmp-agent community {'write' if cm.get('mode') == 'write' else 'read'} simple {_rj_s(cm['name']).replace(' ', '_')}")
        if sd.get("snmp_location"): c.append(f"snmp-agent sys-info location {_rj_s(sd['snmp_location'])}")
        if sd.get("snmp_contact"):  c.append(f"snmp-agent sys-info contact {_rj_s(sd['snmp_contact'])}")
        for h in hosts:
            if isinstance(h, dict) and h.get("ip"):
                c.append(f"snmp-agent target-host trap address udp-domain {_rj_s(h['ip'])} params securityname {_rj_s(h.get('community') or 'public').replace(' ', '_')} v2c")
        if hosts or sd.get("snmp_traps"): c.append("snmp-agent trap enable")
        c.append("#")
    if sd.get("syslog"): c += [f"info-center loghost {_rj_s(sd['syslog'])}", "#"]
    return c

def gen_h3c_comware(data):
    """Generate H3C Comware v7 config (same as v1.1)"""
    config = [
        "#",
        f"# Generated by {APP_NAME} v{APP_VERSION}",
        "# Vendor: H3C · OS: Comware v7",
        "# https://configlabs.online",
        "#"
    ]

    sys_data = data.get("system", {})
    if sys_data:
        if sys_data.get("hostname"):
            config.append(f"sysname {sys_data['hostname']}")
            config.append("#")
        if sys_data.get("timezone"):
            config.append(f"clock timezone {sys_data['timezone']}")
            config.append("#")
        if sys_data.get("ntp"):
            config.append(f"ntp-service unicast-server {sys_data['ntp']}")
            config.append("#")
        if sys_data.get("banner"):
            _bn = str(sys_data['banner']).replace("\r", " ").replace("\n", " ")
            _dl = next((d for d in "%#@$~" if d not in _bn), "%")
            config.append(f"header shell {_dl}{_bn}{_dl}")
            config.append("#")
        config += _h3c_system_extras(sys_data)

    # VLANs (L2)
    for v in data.get("vlans", []):
        if not v.get("vlan"): continue
        config.append(f"vlan {v['vlan']}")
        if v.get("name"): config.append(f" name {v['name']}")
        if v.get("description"): config.append(f" description {v['description']}")
        config.append("#")

    # DHCP pools
    pools = data.get("dhcp_pools", [])
    if pools:
        config.append("dhcp enable")
        config.append("#")
        _fb = []
        for p in pools:
            for ip in str(p.get("forbidden_ips", "") or "").replace(",", " ").split():
                if ip.strip() and ip.strip() not in _fb: _fb.append(ip.strip())
        for ip in _fb:
            _r = [x for x in str(ip).replace("-", " ").split() if x]
            config.append("dhcp server forbidden-ip " + " ".join(_r[:2]))
        if _fb: config.append("#")
        for p in pools:
            if not p.get("pool_name"): continue
            config.append(f"dhcp server ip-pool {p['pool_name']}")
            if p.get("gateway"): config.append(f" gateway-list {p['gateway']}")
            if p.get("network") and p.get("cidr"):
                config.append(f" network {p['network']} mask {cidr_to_mask(p['cidr'])}")
            if p.get("dns"): config.append(f" dns-list {p['dns']}")
            if p.get("lease_days") or p.get("lease_hours"):
                config.append(f" expired day {_rj_s(p.get('lease_days') or 0)}" + (f" hour {_rj_s(p['lease_hours'])}" if p.get("lease_hours") else ""))
            if p.get("domain"): config.append(f" domain-name {p['domain']}")
            if p.get("ac_ip"): config.append(f" option 138 ip-address {_rj_s(p['ac_ip'])}")
            config.append("#")

    # ACLs (before the interfaces that reference them)
    for a in data.get("acls", []):
        num = a.get("acl_number")
        aname = _rj_s(a.get("acl_name"))
        if aname:
            acl_type = "basic" if a.get("acl_type") == "basic" else "advanced"
            config.append(f"acl {acl_type} name {aname}")
        else:
            if not num: continue
            try: n = int(num)
            except: continue
            acl_type = "basic" if 2000 <= n <= 2999 else "advanced"
            config.append(f"acl {acl_type} {n}")
        if a.get("description"): config.append(f" description {_rj_s(a['description'])}")
        _auto = 0
        for rule in a.get("rules", []):
            if not (rule.get("action") and rule.get("source")): continue
            _auto += 5
            rid = (rule.get("rule_id") or "").strip() if isinstance(rule.get("rule_id"), str) else str(rule.get("rule_id") or "")
            rid = rid or str(_auto)
            proto = rule.get("protocol", "ip")
            src = rule["source"]
            if src.lower() == "any":
                line = f" rule {rid} {rule['action']} {proto} source any"
            else:
                wc = rule.get("wildcard") or "0"
                line = f" rule {rid} {rule['action']} {proto} source {src} {wc}"
            if rule.get("src_port"): line += f" source-port {_rj_s(rule['src_port'])}"
            dst = (rule.get("destination") or "").strip()
            if dst and dst.lower() != "any" and acl_type == "advanced":
                line += f" destination {dst} {rule.get('dest_wildcard') or '0'}"
            if rule.get("dst_port") and acl_type == "advanced": line += f" destination-port {_rj_s(rule['dst_port'])}"
            if rule.get("icmp_type"): line += f" icmp-type {_rj_s(rule['icmp_type'])}"
            config.append(" " + " ".join(line.split()).lstrip())
        config.append("#")

    # SVIs (L3 VLAN-interfaces)
    for s in data.get("svis", []):
        if not s.get("vlan"): continue
        config.append(f"interface Vlan-interface{s['vlan']}")
        if s.get("description"): config.append(f" description {s['description']}")
        dhcp_mode = s.get("dhcp_mode", "none")
        if dhcp_mode == "client":
            config.append(" ip address dhcp-alloc")
        elif s.get("ip"):
            try:
                ip_addr, cidr = s["ip"].split("/")
                config.append(f" ip address {ip_addr} {cidr_to_mask(cidr)}")
            except: pass
        if dhcp_mode == "server":
            config.append(" dhcp select server")
            if s.get("dhcp_apply_pool"): config.append(f" dhcp server apply ip-pool {_rj_s(s['dhcp_apply_pool'])}")
        elif dhcp_mode == "relay" and s.get("dhcp_relay"):
            config.append(" dhcp select relay")
            config.append(f" dhcp relay server-address {s['dhcp_relay']}")
        config += _h3c_vrrp(s) + _h3c_pf(s)
        if s.get("shutdown"): config.append(" shutdown")
        config.append("#")

    # Physical interfaces
    _is_router = (sys_data.get("device_type") == "router")
    for i in data.get("interfaces", []):
        if not i.get("interface"): continue
        _nm = _rj_s(i["interface"]); _low = _nm.lower()
        config.append(f"interface {_nm}")
        if i.get("description"): config.append(f" description {_rj_s(i['description'])}")
        mode = i.get("mode", "access")
        _bagg = _low.startswith("bridge-aggregation")
        if i.get("lag") and not _bagg:
            config.append(f" port link-aggregation group {_rj_s(i['lag'])}")
            if i.get("speed"): config.append(f" speed {_rj_s(i['speed'])}")
            if i.get("duplex"): config.append(f" duplex {_rj_s(i['duplex'])}")
            if i.get("shutdown"): config.append(" shutdown")
            config.append("#")
            continue
        if mode == "access":
            config.append(" port link-type access")
            if i.get("vlan"): config.append(f" port access vlan {i['vlan']}")
        elif mode == "trunk":
            config.append(" port link-type trunk")
            config.append(" undo port trunk permit vlan 1")
            for _c in _h3c_vl_lines(i.get("allowed") or ""): config.append(f" port trunk permit vlan {_c}")
            if i.get("pvid"): config.append(f" port trunk pvid vlan {i['pvid']}")
        elif mode == "hybrid":
            config.append(" port link-type hybrid")
            config.append(" undo port hybrid vlan 1")
            for _c in _h3c_vl_lines(i.get("untagged") or ""): config.append(f" port hybrid vlan {_c} untagged")
            for _c in _h3c_vl_lines(i.get("tagged") or ""): config.append(f" port hybrid vlan {_c} tagged")
            if i.get("pvid"): config.append(f" port hybrid pvid vlan {i['pvid']}")
        elif mode == "routed":
            _loop = _low.startswith("loopback")
            if i.get("dot1q"): config.append(f" vlan-type dot1q vid {_rj_s(i['dot1q'])}")
            elif not _is_router and not _loop and "." not in _nm and not _low.startswith(("vlan", "tunnel")):
                config.append(" port link-mode route")
            _ip = str(i.get("ip") or "").strip()
            if _ip.lower() == "dhcp": config.append(" ip address dhcp-alloc")
            elif _ip:
                try:
                    _a, _c = _ip.split("/"); config.append(f" ip address {_rj_s(_a)} {cidr_to_mask(_c)}")
                except Exception: pass
            if i.get("dhcp_relay"):
                config += [" dhcp select relay", f" dhcp relay server-address {_rj_s(i['dhcp_relay'])}"]
            config += _h3c_vrrp(i)
            if i.get("nat_outbound"):
                _no = _rj_s(i["nat_outbound"])
                config.append(f" nat outbound {_no}" if _no.isdigit() else f" nat outbound name {_no}")
        if _bagg and i.get("lag_dynamic"): config.append(" link-aggregation mode dynamic")
        config += _h3c_pf(i)
        if i.get("speed"): config.append(f" speed {_rj_s(i['speed'])}")
        if i.get("duplex"): config.append(f" duplex {_rj_s(i['duplex'])}")
        if mode != "routed":
            if i.get("stp_edge"): config.append(" stp edged-port")
            if i.get("poe"): config.append(" poe enable")
        if i.get("shutdown"): config.append(" shutdown")
        config.append("#")

    # Static routes
    routes = data.get("static_routes", [])
    if routes:
        for r in routes:
            if not (r.get("network") and r.get("cidr") and r.get("next_hop")): continue
            line = f" ip route-static {r['network']} {cidr_to_mask(r['cidr'])} {r['next_hop']}"
            if r.get("preference"): line += f" preference {r['preference']}"
            if r.get("description"): line += f" description {r['description']}"
            config.append(line)
        config.append("#")

    # OSPF
    ospf = data.get("ospf", {})
    if ospf and ospf.get("process_id"):
        if ospf.get("router_id"):
            config.append(f"ospf {ospf['process_id']} router-id {ospf['router_id']}")
        else:
            config.append(f"ospf {ospf['process_id']}")
        if ospf.get("default_originate"):
            config.append(" default-route-advertise" + (" always" if ospf.get("default_originate") == "always" else ""))
        for _pi in ospf.get("passive", []) or []:
            config.append(f" silent-interface {_rj_s(_pi)}")
        _groups = {}
        for net in ospf.get("networks", []):
            if net.get("network") and net.get("cidr"):
                _ar = net.get("area", ospf.get("area"))
                if _ar in (None, ""): continue
                _groups.setdefault(format_area(_ar), []).append(net)
        if not _groups and ospf.get("area") not in (None, ""):
            _groups[format_area(ospf["area"])] = []
        for _ar, _nets in _groups.items():
            config.append(f" area {_ar}")
            for net in _nets:
                config.append(f"  network {net['network']} {cidr_to_wildcard(net['cidr'])}")
        config.append("#")

    pbr = data.get("pbr")
    if pbr and pbr.get("isps"):
        config += gen_comware_pbr(pbr)

    config.append("return")
    return "\n".join(config)

# ============================================================
# CISCO IOS GENERATOR (Catalyst 2960/3750, ISR classic)
# ============================================================
def gen_cisco_ios(data):
    """Generate Cisco IOS config"""
    config = [
        "!",
        f"! Generated by {APP_NAME} v{APP_VERSION}",
        "! Vendor: Cisco · OS: IOS",
        "! https://configlabs.online",
        "!",
        "version 15.2",
        "no service timestamps log datetime msec",
        "no service timestamps debug datetime msec",
        "service password-encryption",
        "!"
    ]

    sys_data = data.get("system", {})
    if sys_data.get("hostname"):
        config.append(f"hostname {sys_data['hostname']}")
        config.append("!")
    if sys_data.get("banner"):
        config.append(f"banner motd ^C {sys_data['banner']} ^C")
        config.append("!")
    if sys_data.get("ntp"):
        config.append(f"ntp server {sys_data['ntp']}")
        config.append("!")
    if sys_data.get("timezone"):
        config.append(f"clock timezone {sys_data['timezone']}")
        config.append("!")

    # DHCP excluded addresses (must be at global level!)
    pools = data.get("dhcp_pools", [])
    for p in pools:
        forbidden = p.get("forbidden_ips", "")
        if forbidden:
            for ip in str(forbidden).replace(",", " ").split():
                if ip.strip():
                    config.append(f"ip dhcp excluded-address {ip.strip()}")
    if any(p.get("forbidden_ips") for p in pools):
        config.append("!")

    # DHCP pools
    for p in pools:
        if not p.get("pool_name"): continue
        config.append(f"ip dhcp pool {p['pool_name']}")
        if p.get("network") and p.get("cidr"):
            config.append(f" network {p['network']} {cidr_to_mask(p['cidr'])}")
        if p.get("gateway"): config.append(f" default-router {p['gateway']}")
        if p.get("dns"): config.append(f" dns-server {p['dns']}")
        if p.get("domain"): config.append(f" domain-name {p['domain']}")
        if p.get("lease_days"): config.append(f" lease {p['lease_days']}")
        config.append("!")

    # VLANs
    for v in data.get("vlans", []):
        if not v.get("vlan"): continue
        config.append(f"vlan {v['vlan']}")
        if v.get("name"): config.append(f" name {v['name']}")
        config.append("!")

    # SVIs (L3 VLAN-interfaces)
    for s in data.get("svis", []):
        if not s.get("vlan"): continue
        config.append(f"interface Vlan{s['vlan']}")
        if s.get("description"): config.append(f" description {s['description']}")
        dhcp_mode = s.get("dhcp_mode", "none")
        if dhcp_mode == "client":
            config.append(" ip address dhcp")
        elif s.get("ip"):
            try:
                ip_addr, cidr = s["ip"].split("/")
                config.append(f" ip address {ip_addr} {cidr_to_mask(cidr)}")
            except: pass
        if dhcp_mode == "relay" and s.get("dhcp_relay"):
            config.append(f" ip helper-address {s['dhcp_relay']}")
        if s.get("shutdown"):
            config.append(" shutdown")
        else:
            config.append(" no shutdown")
        config.append("!")

    # Physical interfaces
    for i in data.get("interfaces", []):
        if not i.get("interface"): continue
        config.append(f"interface {i['interface']}")
        if i.get("description"): config.append(f" description {i['description']}")
        mode = i.get("mode", "access")
        if mode == "access":
            config.append(" switchport mode access")
            if i.get("vlan"): config.append(f" switchport access vlan {i['vlan']}")
        elif mode == "trunk":
            # Trunk encapsulation needed on some IOS devices (not on 2960 which is dot1q-only)
            config.append(" switchport trunk encapsulation dot1q")
            config.append(" switchport mode trunk")
            if i.get("allowed"):
                config.append(f" switchport trunk allowed vlan {normalize_vlan_list(i['allowed'])}")
            if i.get("pvid"):
                config.append(f" switchport trunk native vlan {i['pvid']}")
        elif mode == "hybrid":
            # IOS doesn't have hybrid mode - map to trunk with native VLAN
            config.append(" switchport trunk encapsulation dot1q")
            config.append(" switchport mode trunk")
            if i.get("untagged"):
                config.append(f" switchport trunk native vlan {i['untagged']}")
            if i.get("tagged"):
                config.append(f" switchport trunk allowed vlan {normalize_vlan_list(i['tagged'])}")
        if i.get("stp_edge"):
            config.append(" spanning-tree portfast")
        if i.get("poe"):
            config.append(" power inline auto")
        if i.get("shutdown"):
            config.append(" shutdown")
        else:
            config.append(" no shutdown")
        config.append("!")

    # Static routes
    routes = data.get("static_routes", [])
    if routes:
        for r in routes:
            if not (r.get("network") and r.get("cidr") and r.get("next_hop")): continue
            line = f"ip route {r['network']} {cidr_to_mask(r['cidr'])} {r['next_hop']}"
            if r.get("preference"): line += f" {r['preference']}"
            if r.get("description"): line += f" name {r['description']}"
            config.append(line)
        config.append("!")

    # OSPF
    ospf = data.get("ospf", {})
    if ospf and ospf.get("process_id"):
        config.append(f"router ospf {ospf['process_id']}")
        if ospf.get("router_id"):
            config.append(f" router-id {ospf['router_id']}")
        if ospf.get("area") not in (None, ""):
            area = str(ospf["area"]).strip()
            # IOS accepts both plain number and dotted - use whatever user entered
            for net in ospf.get("networks", []):
                if net.get("network") and net.get("cidr"):
                    wc = cidr_to_wildcard(net["cidr"])
                    config.append(f" network {net['network']} {wc} area {area}")
        config.append("!")

    # ACLs
    for a in data.get("acls", []):
        num = a.get("acl_number")
        if not num: continue
        try: n = int(num)
        except: continue
        # IOS: numbered ACLs still work. Standard = 1-99, 1300-1999. Extended = 100-199, 2000-2699
        # We keep user's number but validate rules
        config.append(f"ip access-list extended {n}")
        if a.get("description"):
            config.append(f" remark {a['description']}")
        for rule in a.get("rules", []):
            if not (rule.get("action") and rule.get("source")): continue
            proto = rule.get("protocol", "ip")
            src = rule["source"]
            if src.lower() == "any":
                line = f" {rule['action']} {proto} any"
            else:
                wc = rule.get("wildcard") or "0.0.0.0"
                line = f" {rule['action']} {proto} {src} {wc}"
            # Destination
            if rule.get("destination"):
                dest = rule["destination"]
                if dest.lower() == "any":
                    line += " any"
                else:
                    dwc = (rule.get("dest_wildcard") or "0.0.0.0")
                    line += f" {dest} {dwc}"
            else:
                line += " any"
            config.append(line)
        config.append("!")

    config.append("end")
    return "\n".join(config)

# ============================================================
# CISCO IOS-XE GENERATOR (Catalyst 9k, modern ISR)
# ============================================================
def gen_cisco_iosxe(data):
    """Generate Cisco IOS-XE config (very similar to IOS, minor tweaks)"""
    # IOS-XE is 95% identical to IOS. The main user-visible differences:
    # - No need for 'switchport trunk encapsulation dot1q' (dot1q is only option)
    # - Default ACLs are named rather than numbered
    # - Uses 'version 16.x' or 'version 17.x'

    config = [
        "!",
        f"! Generated by {APP_NAME} v{APP_VERSION}",
        "! Vendor: Cisco · OS: IOS-XE",
        "! https://configlabs.online",
        "!",
        "version 17.9",
        "no service pad",
        "service timestamps debug datetime msec",
        "service timestamps log datetime msec",
        "service password-encryption",
        "!"
    ]

    sys_data = data.get("system", {})
    if sys_data.get("hostname"):
        config.append(f"hostname {sys_data['hostname']}")
        config.append("!")
    if sys_data.get("banner"):
        config.append(f"banner motd ^C {sys_data['banner']} ^C")
        config.append("!")
    if sys_data.get("ntp"):
        config.append(f"ntp server {sys_data['ntp']}")
        config.append("!")
    if sys_data.get("timezone"):
        config.append(f"clock timezone {sys_data['timezone']}")
        config.append("!")

    # DHCP excluded addresses (global)
    pools = data.get("dhcp_pools", [])
    for p in pools:
        forbidden = p.get("forbidden_ips", "")
        if forbidden:
            for ip in str(forbidden).replace(",", " ").split():
                if ip.strip():
                    config.append(f"ip dhcp excluded-address {ip.strip()}")
    if any(p.get("forbidden_ips") for p in pools):
        config.append("!")

    # DHCP pools (same as IOS)
    for p in pools:
        if not p.get("pool_name"): continue
        config.append(f"ip dhcp pool {p['pool_name']}")
        if p.get("network") and p.get("cidr"):
            config.append(f" network {p['network']} {cidr_to_mask(p['cidr'])}")
        if p.get("gateway"): config.append(f" default-router {p['gateway']}")
        if p.get("dns"): config.append(f" dns-server {p['dns']}")
        if p.get("domain"): config.append(f" domain-name {p['domain']}")
        if p.get("lease_days"): config.append(f" lease {p['lease_days']}")
        config.append("!")

    # VLANs
    for v in data.get("vlans", []):
        if not v.get("vlan"): continue
        config.append(f"vlan {v['vlan']}")
        if v.get("name"): config.append(f" name {v['name']}")
        config.append("!")

    # SVIs
    for s in data.get("svis", []):
        if not s.get("vlan"): continue
        config.append(f"interface Vlan{s['vlan']}")
        if s.get("description"): config.append(f" description {s['description']}")
        dhcp_mode = s.get("dhcp_mode", "none")
        if dhcp_mode == "client":
            config.append(" ip address dhcp")
        elif s.get("ip"):
            try:
                ip_addr, cidr = s["ip"].split("/")
                config.append(f" ip address {ip_addr} {cidr_to_mask(cidr)}")
            except: pass
        if dhcp_mode == "relay" and s.get("dhcp_relay"):
            config.append(f" ip helper-address {s['dhcp_relay']}")
        if s.get("shutdown"):
            config.append(" shutdown")
        else:
            config.append(" no shutdown")
        config.append("!")

    # Physical interfaces (IOS-XE: no need for trunk encapsulation)
    for i in data.get("interfaces", []):
        if not i.get("interface"): continue
        config.append(f"interface {i['interface']}")
        if i.get("description"): config.append(f" description {i['description']}")
        mode = i.get("mode", "access")
        if mode == "access":
            config.append(" switchport mode access")
            if i.get("vlan"): config.append(f" switchport access vlan {i['vlan']}")
        elif mode == "trunk":
            # IOS-XE defaults to dot1q — no encapsulation command needed
            config.append(" switchport mode trunk")
            if i.get("allowed"):
                config.append(f" switchport trunk allowed vlan {normalize_vlan_list(i['allowed'])}")
            if i.get("pvid"):
                config.append(f" switchport trunk native vlan {i['pvid']}")
        elif mode == "hybrid":
            config.append(" switchport mode trunk")
            if i.get("untagged"):
                config.append(f" switchport trunk native vlan {i['untagged']}")
            if i.get("tagged"):
                config.append(f" switchport trunk allowed vlan {normalize_vlan_list(i['tagged'])}")
        if i.get("stp_edge"):
            config.append(" spanning-tree portfast")
        if i.get("poe"):
            config.append(" power inline auto")
        if i.get("shutdown"):
            config.append(" shutdown")
        else:
            config.append(" no shutdown")
        config.append("!")

    # Static routes (same as IOS)
    routes = data.get("static_routes", [])
    if routes:
        for r in routes:
            if not (r.get("network") and r.get("cidr") and r.get("next_hop")): continue
            line = f"ip route {r['network']} {cidr_to_mask(r['cidr'])} {r['next_hop']}"
            if r.get("preference"): line += f" {r['preference']}"
            if r.get("description"): line += f" name {r['description']}"
            config.append(line)
        config.append("!")

    # OSPF (same as IOS)
    ospf = data.get("ospf", {})
    if ospf and ospf.get("process_id"):
        config.append(f"router ospf {ospf['process_id']}")
        if ospf.get("router_id"):
            config.append(f" router-id {ospf['router_id']}")
        if ospf.get("area") not in (None, ""):
            area = str(ospf["area"]).strip()
            for net in ospf.get("networks", []):
                if net.get("network") and net.get("cidr"):
                    wc = cidr_to_wildcard(net["cidr"])
                    config.append(f" network {net['network']} {wc} area {area}")
        config.append("!")

    # ACLs
    for a in data.get("acls", []):
        num = a.get("acl_number")
        if not num: continue
        try: n = int(num)
        except: continue
        config.append(f"ip access-list extended {n}")
        if a.get("description"):
            config.append(f" remark {a['description']}")
        for rule in a.get("rules", []):
            if not (rule.get("action") and rule.get("source")): continue
            proto = rule.get("protocol", "ip")
            src = rule["source"]
            if src.lower() == "any":
                line = f" {rule['action']} {proto} any"
            else:
                wc = rule.get("wildcard") or "0.0.0.0"
                line = f" {rule['action']} {proto} {src} {wc}"
            if rule.get("destination"):
                dest = rule["destination"]
                if dest.lower() == "any":
                    line += " any"
                else:
                    dwc = (rule.get("dest_wildcard") or "0.0.0.0")
                    line += f" {dest} {dwc}"
            else:
                line += " any"
            config.append(line)
        config.append("!")

    config.append("end")
    return "\n".join(config)

# ============================================================
# CISCO NX-OS GENERATOR (Nexus 9000, 7000, 5000 series)
# ============================================================
def gen_cisco_nxos(data):
    """Generate Cisco NX-OS config — significant differences from IOS!"""
    config = [
        "!",
        f"! Generated by {APP_NAME} v{APP_VERSION}",
        "! Vendor: Cisco · OS: NX-OS",
        "! https://configlabs.online",
        "!",
    ]

    # Feature enablement (REQUIRED in NX-OS!)
    features = []
    if data.get("ospf") and data["ospf"].get("process_id"):
        features.append("feature ospf")
    if data.get("dhcp_pools"):
        features.append("feature dhcp")
    # Always enable interface-vlan when SVIs exist
    if data.get("svis"):
        features.append("feature interface-vlan")
    # HSRP could be added in future
    if features:
        config.extend(features)
        config.append("!")

    sys_data = data.get("system", {})
    if sys_data.get("hostname"):
        config.append(f"hostname {sys_data['hostname']}")
        config.append("!")
    if sys_data.get("banner"):
        config.append(f"banner motd ^{sys_data['banner']}^")
        config.append("!")
    if sys_data.get("ntp"):
        config.append(f"ntp server {sys_data['ntp']}")
        config.append("!")
    if sys_data.get("timezone"):
        config.append(f"clock timezone {sys_data['timezone']}")
        config.append("!")

    # DHCP pools (NX-OS has slightly different syntax)
    # NX-OS requires 'service dhcp' and 'ip dhcp relay' at global if using relay
    pools = data.get("dhcp_pools", [])
    if pools:
        config.append("service dhcp")
        config.append("ip dhcp relay")
        # Excluded addresses
        for p in pools:
            forbidden = p.get("forbidden_ips", "")
            if forbidden:
                for ip in str(forbidden).replace(",", " ").split():
                    if ip.strip():
                        config.append(f"ip dhcp excluded-address {ip.strip()}")
        config.append("!")
        # Pools
        for p in pools:
            if not p.get("pool_name"): continue
            config.append(f"ip dhcp pool {p['pool_name']}")
            if p.get("network") and p.get("cidr"):
                config.append(f"  network {p['network']} {cidr_to_mask(p['cidr'])}")
            if p.get("gateway"): config.append(f"  default-router {p['gateway']}")
            if p.get("dns"): config.append(f"  dns-server {p['dns']}")
            if p.get("domain"): config.append(f"  domain-name {p['domain']}")
            if p.get("lease_days"): config.append(f"  lease {p['lease_days']}")
            config.append("!")

    # VLANs
    for v in data.get("vlans", []):
        if not v.get("vlan"): continue
        config.append(f"vlan {v['vlan']}")
        if v.get("name"): config.append(f"  name {v['name']}")
        config.append("!")

    # Router OSPF (NX-OS: must be declared BEFORE interfaces reference it)
    ospf = data.get("ospf", {})
    ospf_pid = None
    if ospf and ospf.get("process_id"):
        ospf_pid = ospf["process_id"]
        config.append(f"router ospf {ospf_pid}")
        if ospf.get("router_id"):
            config.append(f"  router-id {ospf['router_id']}")
        config.append(f"  log-adjacency-changes")
        config.append("!")

    # SVIs (NX-OS: prefix notation for IP! OSPF added on interface!)
    for s in data.get("svis", []):
        if not s.get("vlan"): continue
        config.append(f"interface Vlan{s['vlan']}")
        if s.get("description"): config.append(f"  description {s['description']}")
        config.append("  no shutdown" if not s.get("shutdown") else "  shutdown")
        dhcp_mode = s.get("dhcp_mode", "none")
        if dhcp_mode == "client":
            config.append("  ip address dhcp")
        elif s.get("ip"):
            # NX-OS uses prefix notation!
            try:
                ip_addr, cidr = s["ip"].split("/")
                config.append(f"  ip address {ip_addr}/{cidr}")
            except: pass
        if dhcp_mode == "relay" and s.get("dhcp_relay"):
            config.append(f"  ip dhcp relay address {s['dhcp_relay']}")
        # OSPF on interface (NX-OS style)
        if ospf_pid and ospf.get("area") not in (None, ""):
            area = format_area(ospf["area"])
            # Only enable OSPF on SVI if its subnet matches one of OSPF networks
            if s.get("ip"):
                config.append(f"  ip router ospf {ospf_pid} area {area}")
        config.append("!")

    # Physical interfaces (NX-OS: different naming — Ethernet1/1 not GigabitEthernet0/1)
    for i in data.get("interfaces", []):
        if not i.get("interface"): continue
        # Auto-convert GigabitEthernet to Ethernet for NX-OS style
        iface_name = i["interface"]
        config.append(f"interface {iface_name}")
        if i.get("description"): config.append(f"  description {i['description']}")
        mode = i.get("mode", "access")
        if mode == "access":
            config.append("  switchport")
            config.append("  switchport mode access")
            if i.get("vlan"): config.append(f"  switchport access vlan {i['vlan']}")
        elif mode == "trunk":
            config.append("  switchport")
            config.append("  switchport mode trunk")
            if i.get("allowed"):
                config.append(f"  switchport trunk allowed vlan {normalize_vlan_list(i['allowed'])}")
            if i.get("pvid"):
                config.append(f"  switchport trunk native vlan {i['pvid']}")
        elif mode == "hybrid":
            # NX-OS has no hybrid — emulate with trunk + native
            config.append("  switchport")
            config.append("  switchport mode trunk")
            if i.get("untagged"):
                config.append(f"  switchport trunk native vlan {i['untagged']}")
            if i.get("tagged"):
                config.append(f"  switchport trunk allowed vlan {normalize_vlan_list(i['tagged'])}")
        if i.get("stp_edge"):
            config.append("  spanning-tree port type edge")
        if i.get("shutdown"):
            config.append("  shutdown")
        else:
            config.append("  no shutdown")
        config.append("!")

    # OSPF network statements (NX-OS: added on INTERFACE, but we also allow area config here)
    # Actually on NX-OS the interface-based approach is standard — we did that above.
    # No separate 'network X area Y' block like IOS.

    # Static routes (NX-OS uses prefix notation!)
    routes = data.get("static_routes", [])
    if routes:
        for r in routes:
            if not (r.get("network") and r.get("cidr") and r.get("next_hop")): continue
            # Prefix notation: ip route 10.0.0.0/24 next-hop
            line = f"ip route {r['network']}/{r['cidr']} {r['next_hop']}"
            if r.get("preference"): line += f" {r['preference']}"
            config.append(line)
        config.append("!")

    # ACLs (NX-OS: named, not numbered — but we accept numbers as names)
    for a in data.get("acls", []):
        num = a.get("acl_number")
        if not num: continue
        config.append(f"ip access-list ACL_{num}")
        if a.get("description"):
            config.append(f"  remark {a['description']}")
        seq = 10
        for rule in a.get("rules", []):
            if not (rule.get("action") and rule.get("source")): continue
            proto = rule.get("protocol", "ip")
            src = rule["source"]
            rid = rule.get("rule_id", "").strip() or str(seq)
            if src.lower() == "any":
                line = f"  {rid} {rule['action']} {proto} any"
            else:
                wc = rule.get("wildcard") or "0.0.0.0"
                line = f"  {rid} {rule['action']} {proto} {src} {wc}"
            if rule.get("destination"):
                dest = rule["destination"]
                if dest.lower() == "any":
                    line += " any"
                else:
                    dwc = (rule.get("dest_wildcard") or "0.0.0.0")
                    line += f" {dest} {dwc}"
            else:
                line += " any"
            config.append(line)
            seq += 10
        config.append("!")

    return "\n".join(config)

# ============================================================
# MASTER ROUTER
# ============================================================
# ============================================================
# RUIJIE RGOS GENERATOR (switch / router / WLAN AC + fit AP)
# Syntax from public Ruijie docs + community; verify on your model/version.
# ============================================================
def _rj_s(v):
    """Single-line safe text (no CR/LF injection)."""
    return " ".join(str("" if v is None else v).replace("\r", " ").replace("\n", " ").split())

def _rj_if(name):
    """RGOS wants a space between type and number: 'Gi0/1' -> 'Gi 0/1', 'GigabitEthernet0/1' -> 'GigabitEthernet 0/1'."""
    import re
    n = _rj_s(name)
    m = re.match(r"^([A-Za-z]+)\s*(\d.*)$", n)
    return f"{m.group(1)} {m.group(2)}" if m else n

def _rj_vl(s):
    """'10 20 30-40' / '10,20 to 30' -> '10,20,30-40'"""
    t = _rj_s(s).replace(",", " ").replace(" to ", "-")
    return ",".join(t.split())

def _rj_ip(cidr_ip):
    try:
        a, c = str(cidr_ip).strip().split("/")
        return a.strip(), cidr_to_mask(int(c))
    except Exception:
        return None, None

def _rj_acl_kind(n):
    return "standard" if (1 <= n <= 99 or 1300 <= n <= 1999) else "extended"

def _rj_clean(data):
    """Coerce arbitrary JSON into the shape the Ruijie generator expects (never raises)."""
    def dct(v): return v if isinstance(v, dict) else {}
    def lst(v): return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
    def fix_cidr(o):
        if "cidr" in o:
            t = str(o["cidr"]).strip().lstrip("/")
            o["cidr"] = t if (t.isdigit() and 0 <= int(t) <= 32) else ""
        return o
    d = dct(data)
    out = {k: dct(d.get(k)) for k in ("system", "ospf", "nat", "wlan")}
    for k in ("vlans", "svis", "interfaces", "dhcp_pools", "static_routes", "acls"):
        out[k] = [dict(x) for x in lst(d.get(k))]
    for x in out["dhcp_pools"] + out["static_routes"]: fix_cidr(x)
    out["ospf"] = dict(out["ospf"]); out["ospf"]["networks"] = [fix_cidr(dict(x)) for x in lst(out["ospf"].get("networks"))]
    out["nat"] = dict(out["nat"]); out["nat"]["networks"] = [fix_cidr(dict(x)) for x in lst(out["nat"].get("networks"))]
    out["wlan"] = dict(out["wlan"]); out["wlan"]["ssids"] = [dict(x) for x in lst(out["wlan"].get("ssids"))]
    for a in out["acls"]: a["rules"] = [dict(x) for x in lst(a.get("rules"))]
    if not out["ospf"].get("process_id"): out["ospf"] = {}
    return out

def gen_ruijie_rgos(data, kind="switch"):
    import re
    data = _rj_clean(data)
    label = {"switch": "RGOS Switch", "router": "RGOS Router", "wlan": "WLAN AC / Fit AP"}.get(kind, "RGOS")
    is_l2 = kind in ("switch", "wlan")
    c = ["!", f"! Generated by {APP_NAME} v{APP_VERSION}", f"! Vendor: Ruijie · OS: {label}",
         "! https://configlabs.online", "! Verify on your model/firmware before production use.", "!"]
    W = []   # warnings, printed as comments

    sysd = data.get("system") or {}
    if sysd.get("hostname"):
        c += [f"hostname {_rj_s(sysd['hostname'])}", "!"]
    c += ["service password-encryption", "!"]
    if sysd.get("timezone"):
        tz = _rj_s(sysd["timezone"])
        m = re.match(r"^(\S+)\s+([+-]?\d{1,2})(?::(\d{1,2}))?", tz)
        if m: c += [f"clock timezone {m.group(1)} {int(m.group(2))} {int(m.group(3) or 0)}", "!"]
        else: c += [f"clock timezone {tz}", "!"]
    if sysd.get("ntp"):
        c += [f"ntp server {_rj_s(sysd['ntp'])}", "!"]
    if sysd.get("banner"):
        bn = _rj_s(sysd["banner"]); dl = next((d for d in "#%@$~" if d not in bn), "#")
        c += [f"banner motd {dl}{bn}{dl}", "!"]
    if sysd.get("admin_user") and sysd.get("admin_pass"):
        c += [f"username {_rj_s(sysd['admin_user'])} privilege 15 password {_rj_s(sysd['admin_pass'])}",
              "line vty 0 4", " login local"]
        if sysd.get("ssh"): c += [" transport input ssh"]
        c += ["!"]
    elif sysd.get("admin_user") or sysd.get("admin_pass"):
        W.append("management user needs BOTH username and password; skipped")
    if sysd.get("ssh"):
        c += ["enable service ssh-server", "ip ssh version 2", "!"]
    if sysd.get("snmp_community"):
        com = _rj_s(sysd["snmp_community"]).replace(" ", "_")
        c.append(f"snmp-server community {com} ro")
        if sysd.get("snmp_location"): c.append(f"snmp-server location {_rj_s(sysd['snmp_location'])}")
        if sysd.get("snmp_contact"):  c.append(f"snmp-server contact {_rj_s(sysd['snmp_contact'])}")
        if sysd.get("snmp_host"):
            c += [f"snmp-server host {_rj_s(sysd['snmp_host'])} traps version 2c {com}", "snmp-server enable traps"]
        c.append("!")
    if sysd.get("syslog"):
        c += [f"logging server {_rj_s(sysd['syslog'])}", "!"]

    # ---- DHCP ----
    pools = [p for p in data.get("dhcp_pools", []) if p.get("pool_name")]
    relay_any = any(s.get("dhcp_mode") == "relay" and s.get("dhcp_relay") for s in data.get("svis", [])) or \
                any(i.get("dhcp_relay") for i in data.get("interfaces", []))
    if pools or relay_any:
        c += ["service dhcp", "!"]
    seen_fb = []
    for p in pools:
        for ip in str(p.get("forbidden_ips", "") or "").replace(",", " ").split():
            if ip not in seen_fb: seen_fb.append(ip)
    for ip in seen_fb: c.append(f"ip dhcp excluded-address {_rj_s(ip)}")
    if seen_fb: c.append("!")
    for p in pools:
        c.append(f"ip dhcp pool {_rj_s(p['pool_name']).replace(' ', '_')}")
        if p.get("network") and p.get("cidr"):
            try: c.append(f" network {_rj_s(p['network'])} {cidr_to_mask(p['cidr'])}")
            except Exception: pass
        if p.get("gateway"): c.append(f" default-router {_rj_s(p['gateway'])}")
        if p.get("dns"):     c.append(f" dns-server {_rj_s(p['dns']).replace(',', ' ')}")
        if p.get("domain"):  c.append(f" domain-name {_rj_s(p['domain'])}")
        if p.get("lease_days"): c.append(f" lease {_rj_s(p['lease_days'])}")
        if p.get("ac_ip"):   c.append(f" option 138 ip {_rj_s(p['ac_ip'])}")
        c.append("!")

    # ---- VLANs ----
    for v in data.get("vlans", []):
        if not v.get("vlan"): continue
        c.append(f"vlan {_rj_s(v['vlan'])}")
        if v.get("name"): c.append(f" name {_rj_s(v['name']).replace(' ', '_')}")
        c.append("!")

    # ---- ACLs (defined before they are applied) ----
    def emit_acl(num, desc, rules):
        k = _rj_acl_kind(num)
        hdr = [f"ip access-list {k} {num}"]
        if desc: hdr.append(f" remark {_rj_s(desc)}")
        body = []
        auto = 0
        for r in rules:
            act = str(r.get("action", "")).lower()
            if act not in ("permit", "deny") or not r.get("source"): continue
            auto += 10
            rid = _rj_s(r.get("rule_id")) or str(auto)
            if not rid.isdigit(): rid = str(auto)
            src = _rj_s(r["source"]); wc = _rj_s(r.get("wildcard"))
            def side(a, w):
                if a.lower() == "any": return "any"
                if not w or w in ("0", "0.0.0.0"): return f"host {a}"
                return f"{a} {w}"
            if k == "standard":
                body.append(f" {rid} {act} {side(src, wc)}")
            else:
                proto = str(r.get("protocol") or "ip").lower()
                if proto not in ("ip", "tcp", "udp", "icmp"): proto = "ip"
                dst = _rj_s(r.get("destination")) or "any"
                body.append(f" {rid} {act} {proto} {side(src, wc)} {side(dst, _rj_s(r.get('dest_wildcard')))}")
        if body: c.extend(hdr + body + ["!"])
        else: W.append(f"ACL {num} has no valid rules; skipped")
    for a in data.get("acls", []):
        try: n = int(str(a.get("acl_number", "")).strip())
        except Exception: continue
        if n < 1 or n > 2699: W.append(f"ACL {n}: number out of range, skipped"); continue
        emit_acl(n, a.get("description"), a.get("rules", []))

    nat = data.get("nat") or {}
    nat_out = _rj_if(nat["outside"]) if nat.get("outside") else ""
    nat_nets = [n for n in nat.get("networks", []) if n.get("network") and n.get("cidr") not in (None, "")]
    nat_acl = None
    if kind == "router" and nat_out and nat_nets:
        try: nat_acl = int(str(nat.get("acl_number") or 10))
        except Exception: nat_acl = 10
        if _rj_acl_kind(nat_acl) != "standard": nat_acl = 10; W.append("NAT ACL must be standard (1-99); using 10")
        emit_acl(nat_acl, "NAT-INSIDE", [{"action": "permit", "source": n["network"], "wildcard": cidr_to_wildcard(n["cidr"])} for n in nat_nets])

    # ---- STP ----
    if is_l2 and data.get("interfaces"):
        c += ["spanning-tree", "spanning-tree mode rstp", "!"]

    # ---- interfaces helpers ----
    def acl_lines(o):
        r = []
        if o.get("acl_in"):  r.append(f" ip access-group {_rj_s(o['acl_in'])} in")
        if o.get("acl_out"): r.append(f" ip access-group {_rj_s(o['acl_out'])} out")
        return r
    def vrrp_lines(o):
        if o.get("vrrp_id") and o.get("vrrp_ip"):
            r = [f" vrrp {_rj_s(o['vrrp_id'])} ip {_rj_s(o['vrrp_ip'])}"]
            if o.get("vrrp_prio"): r.append(f" vrrp {_rj_s(o['vrrp_id'])} priority {_rj_s(o['vrrp_prio'])}")
            return r
        return []
    def l2_lines(i):
        mode = i.get("mode", "access"); r = []
        if mode == "access":
            r.append(" switchport mode access")
            if i.get("vlan"): r.append(f" switchport access vlan {_rj_s(i['vlan'])}")
        elif mode == "trunk":
            r.append(" switchport mode trunk")
            if i.get("pvid"): r.append(f" switchport trunk native vlan {_rj_s(i['pvid'])}")
            if i.get("allowed"): r.append(f" switchport trunk allowed vlan only {_rj_vl(i['allowed'])}")
        elif mode == "hybrid":
            r.append(" switchport mode hybrid")
            if i.get("untagged"): r.append(f" switchport hybrid allowed vlan untagged {_rj_vl(i['untagged'])}")
            if i.get("tagged"):   r.append(f" switchport hybrid allowed vlan tagged {_rj_vl(i['tagged'])}")
        return r

    # ---- SVIs ----
    for s in data.get("svis", []):
        if not s.get("vlan"): continue
        c.append(f"interface vlan {_rj_s(s['vlan'])}")
        if s.get("description"): c.append(f" description {_rj_s(s['description'])}")
        dm = s.get("dhcp_mode", "none")
        if dm == "client": c.append(" ip address dhcp")
        elif s.get("ip"):
            a, m = _rj_ip(s["ip"])
            if a: c.append(f" ip address {a} {m}")
        if dm == "relay" and s.get("dhcp_relay"): c.append(f" ip helper-address {_rj_s(s['dhcp_relay'])}")
        c += vrrp_lines(s) + acl_lines(s)
        if s.get("shutdown"): c.append(" shutdown")
        c.append("!")

    # ---- physical / routed interfaces + LAG ----
    ifs = [i for i in data.get("interfaces", []) if i.get("interface")]
    user_names = {_rj_if(i["interface"]).lower() for i in ifs}
    lag_first = {}
    for i in ifs:
        if i.get("lag") and i.get("mode", "access") != "routed":
            lag_first.setdefault(_rj_s(i["lag"]), i)
    nat_out_l = nat_out.lower()
    for i in ifs:
        nm = _rj_if(i["interface"]); mode = i.get("mode", "access")
        c.append(f"interface {nm}")
        if i.get("description"): c.append(f" description {_rj_s(i['description'])}")
        if mode == "routed":
            if is_l2: c.append(" no switchport")
            if i.get("dot1q"): c.append(f" encapsulation dot1Q {_rj_s(i['dot1q'])}")
            if str(i.get("ip", "")).strip().lower() == "dhcp": c.append(" ip address dhcp")
            elif i.get("ip"):
                a, m = _rj_ip(i["ip"])
                if a: c.append(f" ip address {a} {m}")
            role = i.get("nat") or ("outside" if nat_acl and nm.lower() == nat_out_l else "")
            if role in ("inside", "outside"): c.append(f" ip nat {role}")
            if i.get("dhcp_relay"): c.append(f" ip helper-address {_rj_s(i['dhcp_relay'])}")
            c += vrrp_lines(i)
        else:
            if i.get("lag"):
                lg = _rj_s(i["lag"]); md = str(i.get("lag_mode") or "static")
                c.append(f" port-group {lg}" + (f" mode {md}" if md in ("active", "passive") else ""))
            elif is_l2:
                c += l2_lines(i)
                if i.get("stp_edge"): c.append(" spanning-tree portfast")
            elif mode in ("access", "trunk", "hybrid"):
                W.append(f"{nm}: switchport modes are for switches; use Routed (L3) on a router")
            if i.get("poe") and is_l2: c.append(" poe enable")
        c += acl_lines(i)
        if i.get("shutdown"): c.append(" shutdown")
        c.append("!")
    for lg, f in lag_first.items():
        if f"aggregateport {lg}".lower() in user_names: continue
        c.append(f"interface AggregatePort {lg}")
        c += l2_lines(f)
        if f.get("stp_edge"): c.append(" spanning-tree portfast")
        c.append("!")

    # ---- routing ----
    rts = [r for r in data.get("static_routes", []) if r.get("network") and r.get("cidr") not in (None, "") and r.get("next_hop")]
    for r in rts:
        ln = f"ip route {_rj_s(r['network'])} {cidr_to_mask(r['cidr'])} {_rj_s(r['next_hop'])}"
        if r.get("preference"): ln += f" {_rj_s(r['preference'])}"
        c.append(ln)
    if rts: c.append("!")
    ospf = data.get("ospf") or {}
    if ospf.get("process_id"):
        c.append(f"router ospf {_rj_s(ospf['process_id'])}")
        if ospf.get("router_id"): c.append(f" router-id {_rj_s(ospf['router_id'])}")
        if ospf.get("area") not in (None, ""):
            for n in ospf.get("networks", []):
                if n.get("network") and n.get("cidr") not in (None, ""):
                    c.append(f" network {_rj_s(n['network'])} {cidr_to_wildcard(n['cidr'])} area {_rj_s(ospf['area'])}")
        c.append("!")

    # ---- NAT ----
    if nat_acl:
        c += [f"ip nat inside source list {nat_acl} interface {nat_out} overload", "!"]
    elif kind == "router" and (nat_out or nat_nets):
        W.append("NAT needs BOTH an outside interface and at least one inside network; skipped")

    # ---- WLAN AC ----
    wl = data.get("wlan") or {}
    if kind == "wlan" and (wl.get("ssids") or wl.get("ac_ip")):
        if wl.get("ac_ip"):
            c += ["ac-controller", f" capwap ctrl-ip {_rj_s(wl['ac_ip'])}", "!"]
        grp = _rj_s(wl.get("ap_group") or "default").replace(" ", "_")
        ssids, nxt = [], 1
        for s in wl.get("ssids", []):
            if not s.get("name"): continue
            try: sid = int(str(s.get("id") or "").strip())
            except Exception: sid = nxt
            nxt = max(nxt, sid) + 1
            if sid < 1 or sid > 4094: W.append(f"SSID {_rj_s(s['name'])}: id {sid} out of range, skipped"); continue
            pw = _rj_s(s.get("password")); sec = s.get("security", "psk")
            if sec == "psk" and not (8 <= len(pw) <= 63):
                W.append(f"SSID {_rj_s(s['name'])}: WPA2-PSK password must be 8-63 characters; SSID skipped"); continue
            ssids.append((sid, _rj_s(s["name"]), _rj_s(s.get("vlan")), sec, pw))
        for sid, name, vlan, sec, pw in ssids:
            c += [f"wlan-config {sid} {name}", " enable-broad-ssid", "!"]
        if ssids:
            c.append(f"ap-group {grp}")
            for sid, name, vlan, sec, pw in ssids:
                if vlan: c.append(f" interface-mapping {sid} {vlan}")
            c.append("!")
        for sid, name, vlan, sec, pw in ssids:
            if sec == "psk":
                c += [f"wlansec {sid}", " security rsn enable", " security rsn ciphers aes enable",
                      " security rsn akm psk enable", f" security rsn akm psk set-key ascii {pw}", "!"]
    elif kind == "wlan":
        pass

    for w in W: c.append(f"! WARNING: {w}")
    c += ["! Save the config with: write", "end"]
    return "\n".join(c)

def gen_ruijie_switch(data): return gen_ruijie_rgos(data, "switch")
def gen_ruijie_router(data): return gen_ruijie_rgos(data, "router")
def gen_ruijie_wlan(data):   return gen_ruijie_rgos(data, "wlan")

# ============================================================
# CONFIG TRANSLATOR: Cisco IOS / IOS-XE and Ruijie RGOS  ->  H3C Comware v7
# Parser -> ConfigLabs data model -> gen_h3c_comware, plus a report of what
# was translated, what needs review and what was not translated.
# ============================================================
import re as _re_tr

_TR_IFTYPES = {
    "tengigabitethernet": "te", "tengige": "te", "te": "te", "twentyfivegige": "twe", "twe": "twe", "tw": "twe",
    "fortygigabitethernet": "fo", "fortygige": "fo", "fo": "fo", "hundredgige": "hu", "hu": "hu",
    "gigabitethernet": "gi", "gi": "gi", "fastethernet": "fa", "fa": "fa", "ethernet": "eth", "eth": "eth",
    "port-channel": "po", "portchannel": "po", "po": "po", "aggregateport": "po", "ag": "po",
    "loopback": "lo", "lo": "lo", "vlan": "vlan", "vl": "vlan", "tunnel": "tu", "tu": "tu",
}
_TR_H3NAME = {"gi": "GigabitEthernet", "fa": "GigabitEthernet", "eth": "GigabitEthernet", "te": "Ten-GigabitEthernet",
              "twe": "Twenty-FiveGigE", "fo": "FortyGigE", "hu": "HundredGigE", "po": "Bridge-Aggregation",
              "lo": "LoopBack", "vlan": "Vlan-interface", "tu": "Tunnel"}
_TR_PORTS = {"www": 80, "http": 80, "https": 443, "ssh": 22, "telnet": 23, "domain": 53, "ftp": 21, "ftp-data": 20,
             "smtp": 25, "pop3": 110, "imap4": 143, "snmp": 161, "snmptrap": 162, "ntp": 123, "bgp": 179, "tftp": 69,
             "syslog": 514, "ldap": 389, "ldaps": 636, "sip": 5060, "msrpc": 135, "netbios-ssn": 139, "microsoft-ds": 445,
             "bootps": 67, "bootpc": 68, "isakmp": 500, "ntp": 123, "radius": 1812, "tacacs": 49}
_TR_PROTOS = {"ip", "tcp", "udp", "icmp", "ospf", "gre", "esp", "ahp", "igmp", "pim", "ipinip"}
_TR_IGNORE_TOP = ("version ", "service timestamps", "service password-encryption", "service call-home", "no service ",
                  "no ip domain-lookup", "no ip domain lookup", "ip routing", "ip classless", "no ip classless", "end", "exit",
                  "boot ", "license ", "no ip http", "ip subnet-zero", "no ip source-route", "service compress-config",
                  "memory ", "ip domain-name", "ip domain name", "ip cef", "no ip cef", "ipv6 cef", "udld ", "errdisable", "vtp ", "cdp run", "no cdp run",
                  "lldp run", "clock summer-time", "archive", "ip http", "no ip bootp", "no ip finger",
                  "!", "build version", "no aaa new-model", "diagnostic ", "login on-", "enable service ", "wr", "write")

def _tr_ipv4(v):
    m = _re_tr.match(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", str(v))
    return bool(m) and all(int(x) <= 255 for x in m.groups())

def _tr_mask_cidr(m, wildcard=False):
    if not _tr_ipv4(m): return None
    n = 0
    for p in m.split("."): n = (n << 8) | int(p)
    if wildcard: n ^= 0xffffffff
    b = bin(n)[2:].zfill(32)
    return None if "01" in b else b.count("1")

def _tr_blocks(text):
    """Split an IOS-like config into [(lineno, command, [(lineno, child)...])]; banners become one command."""
    lines = str(text).replace("\r", "").split("\n")
    out, cur, i = [], None, 0
    while i < len(lines):
        raw = lines[i]; i += 1; n = i
        st = raw.strip()
        if not st: continue
        if st.startswith("!"):
            cur = None; continue
        m = _re_tr.match(r"^banner\s+(\S+)\s*(.*)$", st)
        if m and raw[:1] not in " \t":
            rest = m.group(2); dl = "^C" if rest.startswith("^C") else (rest[:1] or "#")
            body = rest[len(dl):]; txt = []
            if dl in body: txt.append(body.split(dl, 1)[0])
            else:
                txt.append(body)
                while i < len(lines):
                    ln = lines[i]; i += 1
                    if dl in ln: txt.append(ln.split(dl, 1)[0]); break
                    txt.append(ln)
            out.append((n, "banner " + m.group(1) + " " + " ".join(t.strip() for t in txt if t.strip()), [])); cur = None
            continue
        if raw[:1] in " \t" and cur is not None:
            cur[2].append((n, st))
        else:
            cur = (n, st, []); out.append(cur)
    return out

class _Translator:
    def __init__(self, flavor, member=1, device="auto"):
        self.f = flavor
        try: self.member = max(1, min(int(member), 16))
        except Exception: self.member = 1
        self.dev = device if device in ("auto", "switch", "router") else "auto"
        self.ok = 0; self.review = []; self.skip = []; self.if_map = []; self.acl_map = []; self.notes = []
        self.d = {"system": {}, "vlans": [], "svis": [], "interfaces": [], "dhcp_pools": [], "static_routes": [], "ospf": {}, "acls": []}
        self.acls = {}; self.excl = []; self.nat = []; self._fa_noted = False
        self.members = {}; self.bagg = {}; self.is_router = False

    # --- reporting
    def R(self, n, t, note): self.review.append({"line": n, "text": t[:160], "note": note})
    def S(self, n, t, why): self.skip.append({"line": n, "text": t[:160], "note": why})

    # --- names
    def if_name(self, raw, n=0, t=""):
        s = _re_tr.sub(r"\s+", "", raw)
        m = _re_tr.match(r"^([A-Za-z\-]+)(\d[\d/.]*)$", s)
        key = _TR_IFTYPES.get(m.group(1).lower()) if m else None
        if not key: return None
        nums = m.group(2)
        if key in ("po", "lo", "vlan", "tu"):
            out = _TR_H3NAME[key] + nums
        else:
            base, _, sub = nums.partition(".")
            parts = base.split("/")
            if not self.is_router:
                if len(parts) == 1: parts = [str(self.member), "0", parts[0]]
                elif len(parts) == 2: parts = [str(self.member)] + parts
            out = _TR_H3NAME[key] + "/".join(parts) + ("." + sub if sub else "")
            if key == "fa" and not self._fa_noted:
                self._fa_noted = True; self.R(n, t, "FastEthernet mapped to GigabitEthernet; check the real port speed on the H3C model")
        pretty = raw.strip()
        if not any(x[0] == pretty for x in self.if_map) and key not in ("vlan",):
            clash = [a for a, b in self.if_map if b == out]
            if clash: self.R(n, t or pretty, f"{pretty} and {clash[0]} map to the same H3C port ({out}); check the member/port numbering")
            self.if_map.append((pretty, out))
        return out

    def acl_ref(self, ref, std=None):
        """Cisco/Ruijie ACL number or name -> H3C number (digits) or name."""
        ref = str(ref).strip()
        if ref.isdigit():
            n = int(ref)
            if 1 <= n <= 99: out = 2000 + n
            elif 1300 <= n <= 1999: out = 2000 + (n - 1300)
            elif 100 <= n <= 199: out = 3000 + (n - 100)
            elif 2000 <= n <= 2699: out = 3100 + (n - 2000)
            else: out = n
            out = str(out)
        else:
            out = _re_tr.sub(r"[^A-Za-z0-9_]", "_", ref)[:63]
            if not out or not out[0].isalpha(): out = "ACL_" + out
        if ref != out and not any(x[0] == ref for x in self.acl_map): self.acl_map.append((ref, out))
        return out

    # --- main entry
    def run(self, text):
        blocks = _tr_blocks(text)
        self.total = sum(1 + len(b[2]) for b in blocks)
        sw = any(b[1].startswith(("vlan ", "interface vlan", "interface Vlan")) or any(k[1].startswith("switchport") for k in b[2]) for b in blocks)
        self.is_router = (self.dev == "router") or (self.dev == "auto" and not sw)
        if self.is_router: self.d["system"]["device_type"] = "router"
        self.notes.append("Device treated as a " + ("router (interfaces are routed ports, names kept as-is)" if self.is_router
                          else f"switch (2-part names like 0/1 become {self.member}/0/1; change the member number if this unit is not member {self.member})"))
        self.hidden = 0
        own = ("vlan", "interface", "ip dhcp pool", "router ospf", "ip access-list", "line", "access-list")
        for n, cmd, kids in blocks:
            before = len(self.skip)
            try: self.top(n, cmd, kids)
            except Exception as e: self.S(n, cmd, f"could not be parsed ({type(e).__name__})")
            if kids and len(self.skip) > before and not cmd.lower().startswith(own): self.hidden += len(kids)
        self.finish()
        return self.d

    # --- top-level dispatcher
    def top(self, n, cmd, kids):
        w = cmd.split(); lw = cmd.lower(); sysd = self.d["system"]
        if not w: return
        if lw.startswith(_TR_IGNORE_TOP) or lw in ("end", "exit", "wr", "write"):
            self.ok += 1 + len(kids); return
        if w[0] == "hostname" and len(w) > 1:
            sysd["hostname"] = w[1]; self.ok += 1; return
        if w[0] == "banner":
            sysd["banner"] = cmd.split(None, 2)[2] if len(w) > 2 else ""; self.ok += 1; return
        if lw.startswith("ntp server"):
            ips = [x for x in w[2:] if _tr_ipv4(x) or "." in x]
            if not sysd.get("ntp") and ips: sysd["ntp"] = ips[0]; self.ok += 1
            else: self.R(n, cmd, "only the first NTP server is translated; add the others on the H3C manually")
            return
        if lw.startswith("ntp "): self.S(n, cmd, "NTP option has no mapping yet (authentication, peers, etc.)"); return
        if lw.startswith("clock timezone") and len(w) >= 4:
            try:
                h = int(w[3]); mnt = int(w[4]) if len(w) > 4 else 0
                sysd["timezone"] = f"{w[2]} {'minus' if h < 0 else 'add'} {abs(h):02d}:{mnt:02d}:00"; self.ok += 1
            except Exception: self.S(n, cmd, "timezone format not understood")
            return
        if w[0] == "vlan" and len(w) >= 2:
            if w[1] == "range" or "," in w[1] or "-" in w[1]:
                spec = w[2] if w[1] == "range" and len(w) > 2 else w[1]
                ids = []
                for part in spec.split(","):
                    a, _, b = part.partition("-")
                    if a.isdigit() and (not b or b.isdigit()): ids += range(int(a), int(b or a) + 1)
                if 0 < len(ids) <= 300: [self.d["vlans"].append({"vlan": str(v), "name": ""}) for v in ids]; self.ok += 1
                else: self.S(n, cmd, "VLAN list too large or not understood")
                return
            if w[1].isdigit():
                v = {"vlan": w[1], "name": "", "description": ""}
                for kn, kt in kids:
                    kw = kt.split(None, 1)
                    if kw[0] == "name" and len(kw) > 1: v["name"] = kw[1].replace(" ", "_")[:32]; self.ok += 1
                    elif kw[0] in ("state", "exit"): self.ok += 1
                    else: self.S(kn, kt, "VLAN option has no mapping yet")
                self.d["vlans"].append(v); self.ok += 1; return
        if w[0] == "interface" and len(w) > 1: return self.iface(n, cmd, kids)
        if lw.startswith("ip route "): return self.route(n, cmd)
        if lw.startswith("ip default-gateway") and len(w) > 2 and _tr_ipv4(w[2]):
            self.d["static_routes"].append({"network": "0.0.0.0", "cidr": "0", "next_hop": w[2]}); self.ok += 1; return
        if lw.startswith("ip dhcp excluded-address"):
            ips = [x for x in w[3:] if _tr_ipv4(x)]
            if ips: self.excl.append("-".join(ips[:2])); self.ok += 1
            else: self.S(n, cmd, "excluded-address not understood")
            return
        if lw.startswith("ip dhcp pool") and len(w) > 3: return self.pool(n, w[3], kids)
        if lw in ("service dhcp", "ip dhcp snooping") or lw.startswith("service dhcp"):
            self.ok += 1; return
        if lw.startswith("ip dhcp "): self.S(n, cmd, "DHCP option (snooping, relay options, etc.) has no mapping yet"); return
        if lw.startswith("router ospf"): return self.ospf(n, cmd, kids)
        if lw.startswith(("ip access-list", "access-list")) and not lw.startswith("access-list role"): return self.acl_top(n, cmd, kids)
        if lw.startswith("ip nat inside source list"):
            m = _re_tr.match(r"^ip nat inside source list (\S+) (?:interface (.+?) )?overload$", cmd)
            if m and m.group(2): self.nat.append((n, cmd, m.group(1), m.group(2).strip())); return
            self.S(n, cmd, "only 'list X interface Y overload' NAT is translated (pools and static NAT need manual work)"); return
        if lw.startswith("ip nat "): self.S(n, cmd, "NAT pool / static NAT is not translated yet"); return
        if lw.startswith("snmp-server "): return self.snmp(n, cmd, w)
        if lw.startswith(("logging host", "logging server")) or (w[0] == "logging" and len(w) == 2 and _tr_ipv4(w[1])):
            ip = w[-1]
            if _tr_ipv4(ip) and not sysd.get("syslog"): sysd["syslog"] = ip; self.ok += 1
            else: self.R(n, cmd, "only the first syslog server is translated")
            return
        if lw.startswith("logging "): self.ok += 1; return
        if w[0] == "username" and len(w) >= 3: return self.user(n, cmd, w)
        if lw.startswith(("enable secret", "enable password")): self.S(n, cmd, "enable password: set a role password on the H3C yourself (super password)"); return
        if lw.startswith("spanning-tree"): return self.stp(n, cmd, w)
        if lw.startswith("ip ssh") or lw.startswith("crypto key") or lw == "enable service ssh-server":
            sysd["ssh"] = True; self.ok += 1; return
        if lw.startswith("enable service telnet"): self.R(n, cmd, "telnet is not carried over; H3C output uses SSH only"); return
        if w[0] == "line" and len(w) > 1:
            if w[1] in ("vty", "con", "console", "aux"):
                for kn, kt in kids:
                    kl = kt.lower()
                    if kl.startswith("transport input") and "ssh" in kl: sysd["ssh"] = True; self.ok += 1
                    elif kl.startswith("transport input"): self.R(kn, kt, "telnet is not carried over; H3C output uses SSH only")
                    else: self.ok += 1
                self.ok += 1; return
        if lw.startswith(("wlan-config", "ap-group", "wlansec", "ac-controller", "capwap", "ap-config")):
            self.S(n, cmd, "WLAN AC config is not translated: on H3C use wlan service-template / ap-group / ap on the WX controller"); return
        if lw.startswith(("aaa ", "radius", "tacacs", "dot1x", "mab", "authentication ", "crypto ", "ip sla", "track ", "class-map", "policy-map", "route-map", "ip prefix-list", "router bgp", "router eigrp", "router rip", "mpls", "ip vrf", "vrf ", "ip nbar", "ntp authenticate", "ip dhcp snooping")):
            self.S(n, cmd, "feature not translated yet in this version")
            return
        self.S(n, cmd, "no mapping for this command yet")

    # --- static route
    def route(self, n, cmd):
        w = cmd.split()
        if len(w) >= 5 and w[2] == "vrf": self.S(n, cmd, "VRF routes are not translated yet"); return
        if len(w) < 5 or not _tr_ipv4(w[2]) or not _tr_ipv4(w[3]): self.S(n, cmd, "route format not understood"); return
        c = _tr_mask_cidr(w[3])
        if c is None: self.S(n, cmd, "non-contiguous mask"); return
        if not _tr_ipv4(w[4]): self.S(n, cmd, "route via an interface is not translated; use a next-hop address"); return
        r = {"network": w[2], "cidr": str(c), "next_hop": w[4]}
        if len(w) > 5 and w[5].isdigit(): r["preference"] = w[5]
        if "permanent" in w or "tag" in w or "track" in w: self.R(n, cmd, "extra route keywords (tag/track/permanent) dropped")
        self.d["static_routes"].append(r); self.ok += 1

    # --- DHCP pool
    def pool(self, n, name, kids):
        p = {"pool_name": _re_tr.sub(r"[^A-Za-z0-9_-]", "_", name)[:63], "network": "", "cidr": "", "gateway": "", "dns": "", "domain": "", "lease_days": "", "forbidden_ips": ""}
        for kn, kt in kids:
            kw = kt.split(); k = kw[0].lower() if kw else ""
            if k == "network" and len(kw) >= 2 and _tr_ipv4(kw[1]):
                if len(kw) >= 3: c = _tr_mask_cidr(kw[2].lstrip("/")) if "." in kw[2] else (int(kw[2].lstrip("/")) if kw[2].lstrip("/").isdigit() and int(kw[2].lstrip("/")) <= 32 else None)
                else: c = None
                p["network"] = kw[1]; p["cidr"] = str(c) if c is not None else ""; self.ok += 1
                if c is None: self.R(kn, kt, "network mask not understood: set the pool network manually")
            elif k == "default-router" and len(kw) > 1: p["gateway"] = kw[1]; self.ok += 1
            elif k == "dns-server": p["dns"] = " ".join(kw[1:3]); self.ok += 1
            elif k == "domain-name" and len(kw) > 1: p["domain"] = kw[1]; self.ok += 1
            elif k == "lease" and len(kw) > 1:
                if kw[1].isdigit(): p["lease_days"] = kw[1]; self.ok += 1
                if len(kw) > 2 and kw[2].isdigit() and int(kw[2]) > 0: p["lease_hours"] = kw[2]
                if len(kw) > 3 and kw[3].isdigit() and int(kw[3]) > 0: self.R(kn, kt, "lease minutes dropped (H3C: days and hours)")
                if kw[1] == "infinite": p["lease_days"] = ""; self.R(kn, kt, "infinite lease: set 'expired unlimited' on the H3C manually")
            elif k == "option" and len(kw) >= 4 and kw[1] == "138" and kw[2] == "ip": p["ac_ip"] = kw[3]; self.ok += 1
            else: self.S(kn, kt, "DHCP pool option has no mapping yet")
        self.d["dhcp_pools"].append(p); self.ok += 1

    # --- OSPF
    def ospf(self, n, cmd, kids):
        w = cmd.split()
        if len(w) < 3 or not w[2].isdigit(): self.S(n, cmd, "OSPF process not understood"); return
        if self.d["ospf"].get("process_id"):
            self.S(n, cmd, "only one OSPF process is translated"); return
        o = {"process_id": w[2], "router_id": "", "area": "", "networks": [], "passive": []}
        for kn, kt in kids:
            kw = kt.split(); k = kt.lower()
            if kw[0] == "router-id" and len(kw) > 1: o["router_id"] = kw[1]; self.ok += 1
            elif kw[0] == "network" and len(kw) >= 5 and kw[3] == "area":
                c = _tr_mask_cidr(kw[2], True)
                if c is None: self.S(kn, kt, "non-contiguous wildcard"); continue
                o["networks"].append({"network": kw[1], "cidr": str(c), "area": kw[4]})
                if not o["area"]: o["area"] = kw[4]
                self.ok += 1
            elif kw[0] == "passive-interface" and len(kw) > 1:
                if kw[1] == "default": self.R(kn, kt, "passive-interface default: list the silent interfaces on the H3C manually")
                else:
                    nm = self.if_name(" ".join(kw[1:]), kn, kt)
                    if nm: o["passive"].append(nm); self.ok += 1
                    else: self.S(kn, kt, "interface name not understood")
            elif k.startswith("default-information originate"):
                o["default_originate"] = "always" if "always" in kw else True; self.ok += 1
            elif k.startswith("auto-cost"): self.ok += 1; self.R(kn, kt, "dropped: set 'bandwidth-reference' on the H3C if you changed it")
            elif k.startswith(("log-adjacency", "nsr", "exit")): self.ok += 1
            else: self.S(kn, kt, "OSPF option has no mapping yet (redistribute, area types, summaries...)")
        self.d["ospf"] = o; self.ok += 1

    # --- ACL
    def acl_top(self, n, cmd, kids):
        w = cmd.split()
        if w[0] == "access-list":   # numbered one-liner
            if len(w) < 4 or not w[1].isdigit(): self.S(n, cmd, "access-list not understood"); return
            num = int(w[1]); std = (1 <= num <= 99 or 1300 <= num <= 1999)
            self.acl_rule(w[1], std, n, cmd, w[2:]); return
        if len(w) < 4 or w[2] not in ("standard", "extended"): self.S(n, cmd, "ACL type not understood"); return
        std = (w[2] == "standard"); ref = w[3]
        for kn, kt in kids: self.acl_rule(ref, std, kn, kt, kt.split())
        self.ok += 1
        self.acls.setdefault(ref, self.acls.get(ref) or {"std": std, "rules": [], "desc": ""})

    def acl_rule(self, ref, std, n, text, toks):
        a = self.acls.setdefault(ref, {"std": std, "rules": [], "desc": ""})
        a["std"] = std
        seq = ""
        if toks and toks[0].isdigit() and len(toks) > 1 and toks[1] in ("permit", "deny", "remark"): seq = toks[0]; toks = toks[1:]
        if not toks: return
        if toks[0] == "remark":
            if not a["desc"]: a["desc"] = " ".join(toks[1:])[:240]; self.ok += 1
            else: self.R(n, text, "extra remark dropped (H3C ACL keeps one description)")
            return
        if toks[0] not in ("permit", "deny"): self.S(n, text, "ACL entry not understood"); return
        try:
            r, why = self._rule(toks, std)
        except IndexError: r, why = None, "entry is incomplete"
        if r is None: self.S(n, text, why or "ACL entry not translated"); return
        if seq: r["rule_id"] = seq
        a["rules"].append(r); self.ok += 1

    def _addr(self, t, i, std):
        x = t[i]
        if x == "any": return "any", "", i + 1
        if x == "host": return t[i + 1], "0", i + 2
        if _tr_ipv4(x):
            if i + 1 < len(t) and _tr_ipv4(t[i + 1]): return x, t[i + 1], i + 2
            if std: return x, "0", i + 1
        raise IndexError

    def _port(self, t, i):
        if i < len(t) and t[i] in ("eq", "neq", "gt", "lt", "range"):
            op = t[i]; need = 2 if op == "range" else 1
            vals = []
            for v in t[i + 1:i + 1 + need]:
                if v.isdigit(): vals.append(v)
                elif v in _TR_PORTS: vals.append(str(_TR_PORTS[v]))
                else: raise KeyError(v)
            return f"{op} {' '.join(vals)}", i + 1 + need
        return "", i

    def _rule(self, t, std):
        act = t[0]; r = {"action": act, "protocol": "ip"}; i = 1
        if std:
            s, wc, i = self._addr(t, i, True); r["source"] = s; r["wildcard"] = wc
            rest = t[i:]
        else:
            proto = t[i]; i += 1
            if proto.isdigit() or proto not in _TR_PROTOS: return None, f"protocol '{proto}' not supported"
            r["protocol"] = proto
            s, wc, i = self._addr(t, i, False); r["source"] = s; r["wildcard"] = wc
            try:
                if proto in ("tcp", "udp"): sp, i = self._port(t, i); 
                else: sp = ""
            except KeyError as e: return None, f"port name {e} not mapped"
            if sp: r["src_port"] = sp
            d, dwc, i = self._addr(t, i, False); r["destination"] = d; r["dest_wildcard"] = dwc
            try:
                if proto in ("tcp", "udp"): dp, i = self._port(t, i)
                else: dp = ""
            except KeyError as e: return None, f"port name {e} not mapped"
            if dp: r["dst_port"] = dp
            if proto == "icmp" and i < len(t) and t[i] not in ("log", "log-input"):
                if t[i] in ("echo", "echo-reply"): r["icmp_type"] = t[i]; i += 1
                else: return None, f"ICMP type '{t[i]}' not mapped"
            rest = t[i:]
        extra = [x for x in rest if x not in ("log", "log-input")]
        if extra: return None, "option '" + extra[0] + "' (established / dscp / time-range ...) is not translated"
        if len(rest) != len(extra): self.notes.append("'log' keyword on ACL entries was dropped") if "'log' keyword on ACL entries was dropped" not in self.notes else None
        return r, ""

    # --- interface
    def iface(self, n, cmd, kids):
        rest = cmd.split(None, 1)[1]
        names = [rest]
        if rest.lower().startswith("range "):
            names = []
            for part in rest[6:].split(","):
                part = part.strip(); m = _re_tr.match(r"^([A-Za-z\-]+)\s*([\d/]*?/)?(\d+)\s*-\s*(\d+)$", part)
                if m and int(m.group(4)) - int(m.group(3)) < 96:
                    names += [f"{m.group(1)}{m.group(2) or ''}{k}" for k in range(int(m.group(3)), int(m.group(4)) + 1)]
                elif part: names.append(part)
        if not names: self.S(n, cmd, "interface range not understood"); return
        it = self.kids(kids)
        for nm in names:
            self.one_iface(n, cmd, nm, it)
        self.ok += 1

    def kids(self, kids):
        it = {"desc": "", "shut": False, "mode": "", "vlan": "", "allowed": None, "add": [], "pvid": "", "untag": "", "tag": "", "edge": False,
              "poe": False, "lag": "", "lagmode": "", "ip": "", "dhcp": False, "relay": "", "acl_in": "", "acl_out": "", "vrrp": {}, "nat": "",
              "dot1q": "", "noswitchport": False, "speed": "", "duplex": ""}
        def vr(g):
            g = "1" if g in ("0", "") else g
            return it["vrrp"].setdefault(g, {"id": g, "ip": "", "priority": ""})
        for n, t in kids:
            w = t.split(); lw = t.lower(); k = w[0].lower()
            if lw == "no shutdown" or k == "exit": self.ok += 1; continue
            if lw == "no switchport": it["noswitchport"] = True; self.ok += 1; continue
            if lw.startswith("no ip address"): self.ok += 1; continue
            if k == "no": self.ok += 1; continue
            if k == "description": it["desc"] = t.split(None, 1)[1][:240] if len(w) > 1 else ""; self.ok += 1
            elif k == "shutdown": it["shut"] = True; self.ok += 1
            elif lw.startswith("switchport mode"):
                m = w[2] if len(w) > 2 else ""
                if m in ("access", "trunk", "hybrid"): it["mode"] = m; self.ok += 1
                else: self.R(n, t, "dynamic switchport mode: pick access or trunk on the H3C")
            elif lw.startswith("switchport access vlan") and len(w) > 3: it["vlan"] = w[3]; self.ok += 1
            elif lw.startswith("switchport trunk native vlan") and len(w) > 4: it["pvid"] = w[4]; self.ok += 1
            elif lw.startswith("switchport hybrid native vlan") and len(w) > 4: it["pvid"] = w[4]; self.ok += 1
            elif lw.startswith("switchport hybrid allowed vlan") and len(w) > 5:
                key = "untag" if w[4] == "untagged" else "tag" if w[4] == "tagged" else ""
                if key: it[key] = ",".join(filter(None, [it[key], w[5]])); self.ok += 1
                else: self.S(n, t, "hybrid VLAN option not understood")
            elif lw.startswith("switchport trunk allowed vlan") and len(w) > 4:
                a = w[4]
                if a in ("add",) and len(w) > 5:
                    if it["allowed"] is None: self.R(n, t, "'add' without a base list: check which VLANs this trunk should carry")
                    else: it["allowed"] += "," + w[5]
                    it["add"].append(w[5]); self.ok += 1
                elif a in ("only",) and len(w) > 5: it["allowed"] = w[5]; self.ok += 1
                elif a == "all": it["allowed"] = "all"; self.ok += 1
                elif a in ("remove", "except", "none"): self.R(n, t, "VLAN 'remove/except/none': write the allowed list explicitly on the H3C")
                else: it["allowed"] = a; self.ok += 1
            elif lw.startswith(("switchport trunk encapsulation", "switchport nonegotiate", "switchport voice vlan", "cdp ", "lldp ", "load-interval", "negotiation", "mdix", "duplex auto", "speed auto", "ip proxy-arp", "ip redirects", "ip unreachables", "keepalive", "flowcontrol", "logging event")):
                self.ok += 1 if not lw.startswith("switchport voice") else 0
                if lw.startswith("switchport voice"): self.S(n, t, "voice VLAN has no mapping yet (use voice-vlan on H3C)")
            elif lw.startswith("spanning-tree portfast") or lw.startswith("spanning-tree edge"): it["edge"] = True; self.ok += 1
            elif lw.startswith("spanning-tree bpduguard") : self.d["system"]["bpdu_guard"] = True; self.ok += 1
            elif lw.startswith("power inline"):
                if "never" in lw: self.R(n, t, "PoE off: add 'undo poe enable' on the H3C port")
                else: it["poe"] = True; self.ok += 1
            elif lw.startswith("channel-group") and len(w) > 1:
                it["lag"] = w[1]; mode = w[3] if len(w) > 3 and w[2] == "mode" else ""
                it["lagmode"] = "dynamic" if mode in ("active", "passive") else ""
                if mode in ("desirable", "auto"): self.R(n, t, "PAgP is Cisco-only; converted to a static aggregation")
                self.ok += 1
            elif k == "port-group" and len(w) > 1:
                it["lag"] = w[1]; it["lagmode"] = "dynamic" if (len(w) > 3 and w[2] == "mode" and w[3] in ("active", "passive")) else ""; self.ok += 1
            elif lw.startswith("ip address dhcp"): it["dhcp"] = True; self.ok += 1
            elif lw.startswith("ip address") and len(w) >= 4:
                if "secondary" in w: self.R(n, t, "secondary IP dropped; add it on the H3C with 'ip address ... sub'"); continue
                c = _tr_mask_cidr(w[3])
                if _tr_ipv4(w[2]) and c is not None: it["ip"] = f"{w[2]}/{c}"; self.ok += 1
                else: self.S(n, t, "IP address not understood")
            elif lw.startswith("ip helper-address") and len(w) > 2:
                if it["relay"]: self.R(n, t, "only the first helper address is translated")
                else: it["relay"] = w[2]; self.ok += 1
            elif lw.startswith("ip access-group") and len(w) >= 4:
                ref = self.acl_ref(w[2]);
                if w[3] == "in": it["acl_in"] = ref; self.ok += 1
                elif w[3] == "out": it["acl_out"] = ref; self.ok += 1
                else: self.S(n, t, "ACL direction not understood")
            elif k == "vrrp" and len(w) >= 3 and w[1].isdigit():
                g = vr(w[1]); s = w[2].lower()
                if s == "ip" and len(w) > 3: g["ip"] = w[3]; self.ok += 1
                elif s == "priority" and len(w) > 3: g["priority"] = w[3]; self.ok += 1
                elif s == "preempt": self.ok += 1
                else: self.S(n, t, "VRRP option has no mapping yet (timers, track, authentication)")
            elif k == "standby" and len(w) >= 2:
                gid = w[1] if w[1].isdigit() else "0"; rest = w[2:] if w[1].isdigit() else w[1:]
                if rest[:1] == ["version"]: self.ok += 1; continue
                g = vr(gid); s = rest[0].lower() if rest else ""
                if s == "ip" and len(rest) > 1:
                    g["ip"] = rest[1]; self.ok += 1
                    self.R(n, t, "HSRP converted to VRRP: a different protocol, so both peers must be migrated together" + ("; group 0 became VRRP group 1" if gid == "0" else ""))
                elif s == "priority" and len(rest) > 1: g["priority"] = rest[1]; self.ok += 1
                elif s == "preempt": self.ok += 1
                else: self.S(n, t, "HSRP option has no mapping yet (timers, track, authentication)")
            elif lw in ("ip nat inside", "ip nat outside"): it["nat"] = w[2]; self.ok += 1
            elif k == "encapsulation" and len(w) >= 3 and w[1].lower() == "dot1q": it["dot1q"] = w[2]; self.ok += 1
            elif k == "speed" and len(w) > 1 and w[1].isdigit(): it["speed"] = w[1]; self.ok += 1
            elif k == "duplex" and len(w) > 1 and w[1] in ("full", "half"): it["duplex"] = w[1]; self.ok += 1
            elif lw.startswith(("ip ospf", "ip pim", "ip igmp")): self.S(n, t, "interface-level routing option has no mapping yet")
            elif lw.startswith(("switchport port-security", "storm-control", "ip dhcp snooping", "service-policy", "mls qos", "ip verify", "ip arp inspection", "authentication", "dot1x", "mab")):
                self.S(n, t, "security / QoS feature not translated yet")
            else: self.S(n, t, "no mapping for this interface command yet")
        it["vrrp"] = [g for g in it["vrrp"].values() if g["ip"]]
        return it

    def one_iface(self, n, cmd, raw, it):
        h3 = self.if_name(raw, n, cmd)
        if not h3: self.S(n, cmd, f"interface type '{raw}' not understood"); return
        key = _TR_IFTYPES.get(_re_tr.match(r"^([A-Za-z\-]+)", _re_tr.sub(r"\s+", "", raw)).group(1).lower())
        if key == "vlan":
            vid = _re_tr.sub(r"\D", "", raw)
            ip = it["ip"]; dm = "client" if it["dhcp"] else ("relay" if it["relay"] else "none")
            self.d["svis"].append({"vlan": vid, "description": it["desc"], "ip": ip, "dhcp_mode": dm, "dhcp_relay": it["relay"],
                                   "shutdown": it["shut"], "vrrp": it["vrrp"], "acl_in": it["acl_in"], "acl_out": it["acl_out"]}); return
        e = {"interface": h3, "description": it["desc"], "shutdown": it["shut"], "speed": it["speed"], "duplex": it["duplex"],
             "acl_in": it["acl_in"], "acl_out": it["acl_out"]}
        if key == "po":
            e.update(self._l2(it, "trunk")); self.bagg[_re_tr.sub(r"\D", "", raw)] = e; self.d["interfaces"].append(e); return
        if it["lag"]:
            e["lag"] = it["lag"]; e["mode"] = it["mode"] or "access"
            self.members.setdefault(it["lag"], []).append((e, it)); self.d["interfaces"].append(e); return
        routed = key == "lo" or it["noswitchport"] or bool(it["dot1q"]) or (self.is_router) or (it["ip"] and not it["mode"]) or it["dhcp"]
        if routed:
            e["mode"] = "routed"; e["ip"] = "dhcp" if it["dhcp"] else it["ip"]; e["dot1q"] = it["dot1q"]
            e["dhcp_relay"] = it["relay"]; e["vrrp"] = it["vrrp"]; e["nat_side"] = it["nat"]
        else:
            e.update(self._l2(it, "access")); e["stp_edge"] = it["edge"]; e["poe"] = it["poe"]
        self.d["interfaces"].append(e)

    def _l2(self, it, default):
        mode = it["mode"] or ("trunk" if (it["allowed"] or it["pvid"]) and default == "access" else default)
        out = {"mode": mode}
        if mode == "access": out["vlan"] = it["vlan"]
        elif mode == "trunk":
            if it["allowed"] and it["allowed"] != "all": out["allowed"] = it["allowed"]
            elif it["allowed"] == "all": out["allowed"] = "all"
            out["pvid"] = it["pvid"]
        else:
            out["untagged"] = it["untag"]; out["tagged"] = it["tag"]; out["pvid"] = it["pvid"]
        return out

    # --- misc
    def snmp(self, n, cmd, w):
        sd = self.d["system"]
        if len(w) >= 3 and w[1] == "community":
            ro = "RW" in [x.upper() for x in w[3:]] or "rw" in w[3:]
            sd.setdefault("snmp_communities", []).append({"name": w[2], "mode": "write" if ro else "read"}); self.ok += 1
            if len(w) > 4 and w[4].isdigit(): self.R(n, cmd, "SNMP community ACL dropped")
        elif w[1] == "location": sd["snmp_location"] = cmd.split(None, 2)[2] if len(w) > 2 else ""; self.ok += 1
        elif w[1] == "contact": sd["snmp_contact"] = cmd.split(None, 2)[2] if len(w) > 2 else ""; self.ok += 1
        elif w[1] == "host" and len(w) >= 3 and _tr_ipv4(w[2]):
            comm = w[-1] if len(w) > 3 else "public"
            if "version" in w and w[w.index("version") + 1] not in ("1", "2c"): self.S(n, cmd, "SNMPv3 hosts are not translated yet"); return
            sd.setdefault("snmp_hosts", []).append({"ip": w[2], "community": comm}); self.ok += 1
        elif w[1] == "enable" and len(w) > 2 and w[2] == "traps": sd["snmp_traps"] = True; self.ok += 1
        elif w[1] in ("trap-source", "trap", "ifindex", "chassis-id", "system-shutdown", "queue-length"): self.ok += 1
        else: self.S(n, cmd, "SNMP option has no mapping yet (SNMPv3 users/groups/views)")

    def user(self, n, cmd, w):
        sd = self.d["system"]
        if sd.get("admin_user"): self.R(n, cmd, "only the first user is translated; create the others with 'local-user' on the H3C"); return
        sd["admin_user"] = w[1]
        m = _re_tr.search(r"\b(password|secret)\s+(?:(\d)\s+)?(\S+)", cmd)
        if m and (m.group(2) in (None, "0")) and m.group(1) == "password": sd["admin_pass"] = m.group(3); self.ok += 1
        else:
            self.R(n, cmd, "the password is hashed or a 'secret', so it cannot be carried over: set the password on the H3C")
        if "privilege" in w and w[w.index("privilege") + 1:][:1] not in (["15"],): self.R(n, cmd, "user role: non-15 privilege mapped to network-admin, adjust the role")

    def stp(self, n, cmd, w):
        sd = self.d["system"]
        if len(w) >= 3 and w[1] == "mode":
            m = {"rapid-pvst": "pvst", "pvst": "pvst", "mst": "mstp", "mstp": "mstp", "rstp": "rstp", "stp": "rstp"}.get(w[2])
            if m: sd["stp_mode"] = m; self.ok += 1
            if w[2] in ("rapid-pvst", "pvst"): self.R(n, cmd, "PVST needs an H3C model that supports it; use stp mode rstp or mstp otherwise")
            if w[2] == "stp": self.R(n, cmd, "classic STP mapped to RSTP (compatible)")
            if not m: self.S(n, cmd, "STP mode not understood")
        elif cmd.strip() in ("spanning-tree",): self.ok += 1
        elif "portfast" in cmd and "default" in cmd: self.ok += 1
        elif "bpduguard" in cmd and "default" in cmd: sd["bpdu_guard"] = True; self.ok += 1
        elif "vlan" in cmd and "priority" in cmd or "mst" in cmd or "priority" in cmd: self.S(n, cmd, "STP priority / MST instance is not translated yet: set 'stp priority' / 'stp region-configuration' on the H3C")
        else: self.S(n, cmd, "STP option has no mapping yet")

    def finish(self):
        d = self.d
        # LAG: make sure every aggregation has its Bridge-Aggregation interface
        for lg, mems in self.members.items():
            dyn = any(it["lagmode"] == "dynamic" for _, it in mems)
            if lg not in self.bagg:
                e = {"interface": "Bridge-Aggregation" + lg, "description": "", "shutdown": False}
                e.update(self._l2(mems[0][1], "trunk")); d["interfaces"].append(e); self.bagg[lg] = e
            self.bagg[lg]["lag_dynamic"] = dyn
            for e, it in mems: e["lag"] = lg
        # NAT -> nat outbound on the outside interface
        by = {x["interface"]: x for x in d["interfaces"]}
        for n, cmd, acl, ifc in self.nat:
            nm = self.if_name(ifc, n, cmd)
            if nm and nm in by: by[nm]["nat_outbound"] = self.acl_ref(acl); self.ok += 1
            else: self.R(n, cmd, "NAT outside interface not found in this config")
        for x in d["interfaces"]: x.pop("nat_side", None)
        # DHCP excluded addresses: attach to the pool that contains them
        for ex in self.excl:
            first = ex.split("-")[0]; placed = False
            for p in d["dhcp_pools"]:
                try:
                    import ipaddress
                    if p["network"] and p["cidr"] and ipaddress.ip_address(first) in ipaddress.ip_network(f"{p['network']}/{p['cidr']}", strict=False):
                        p["forbidden_ips"] = (p["forbidden_ips"] + " " + ex).strip(); placed = True; break
                except Exception: pass
            if not placed and d["dhcp_pools"]:
                d["dhcp_pools"][0]["forbidden_ips"] = (d["dhcp_pools"][0]["forbidden_ips"] + " " + ex).strip()
            elif not placed: self.R(0, "ip dhcp excluded-address " + ex, "no DHCP pool in this config to attach it to")
        # ACLs
        for ref, a in self.acls.items():
            out = self.acl_ref(ref)
            ent = {"acl_type": "basic" if a["std"] else "advanced", "description": a["desc"], "rules": []}
            if out.isdigit(): ent["acl_number"] = out
            else: ent["acl_name"] = out
            auto = 0
            for r in a["rules"]:
                auto += 10
                r = dict(r); r.setdefault("rule_id", str(auto)); ent["rules"].append(r)
            d["acls"].append(ent)
        if d["ospf"] and not d["ospf"].get("process_id"): d["ospf"] = {}
        for e in d["interfaces"]:
            if e.get("lag_dynamic") is None and e["interface"].lower().startswith("bridge-aggregation"): e["lag_dynamic"] = False

    def report(self):
        review = sorted(self.review, key=lambda x: x["line"]); skip = sorted(self.skip, key=lambda x: x["line"])
        return {"total": self.total, "ok": self.ok, "review": review[:300], "skipped": skip[:400], "review_count": len(self.review), "skipped_count": len(self.skip) + getattr(self, "hidden", 0),
                "interface_map": [{"from": a, "to": b} for a, b in self.if_map[:300]], "acl_map": [{"from": a, "to": b} for a, b in self.acl_map[:100]], "notes": self.notes}

def translate_config(source, text, member=1, device="auto"):
    """source: 'cisco' (IOS / IOS-XE) or 'ruijie' (RGOS). Returns (h3c_config, report, data)."""
    tr = _Translator("ruijie" if source == "ruijie" else "cisco", member, device)
    data = tr.run(text)
    cfg = gen_h3c_comware(data)
    rep = tr.report()
    todo = ["#", "# ===== NOT TRANSLATED: review these lines by hand ====="]
    for s in tr.skip[:200]: todo.append("# [" + str(s["line"]) + "] " + _rj_s(s["text"]) + "   <- " + s["note"])
    for r in tr.review[:200]: todo.append("# [CHECK " + str(r["line"]) + "] " + _rj_s(r["text"]) + "   <- " + r["note"])
    if len(todo) > 2:
        head, sep, tail = cfg.rpartition("\nreturn")
        cfg = (head + "\n" + "\n".join(todo) + "\n#\nreturn") if sep else cfg + "\n" + "\n".join(todo)
    return cfg, rep, data

def generate_config(vendor, os_id, data):
    """Route to the correct generator based on vendor+OS"""
    if vendor == "h3c" and os_id == "comware":
        return gen_h3c_comware(data)
    elif vendor == "cisco" and os_id == "ios":
        return gen_cisco_ios(data)
    elif vendor == "cisco" and os_id == "iosxe":
        return gen_cisco_iosxe(data)
    elif vendor == "cisco" and os_id == "nxos":
        return gen_cisco_nxos(data)
    elif vendor == "ruijie" and os_id == "rgos_switch":
        return gen_ruijie_switch(data)
    elif vendor == "ruijie" and os_id == "rgos_router":
        return gen_ruijie_router(data)
    elif vendor == "ruijie" and os_id == "rgos_wlan":
        return gen_ruijie_wlan(data)
    else:
        return f"# Vendor '{vendor}' with OS '{os_id}' is not yet supported.\n# Coming soon!"

# ============================================================
# TEMPLATES (tagged by vendor + OS)
# ============================================================
TEMPLATES = {
    # =========== H3C COMWARE ===========
    "h3c_comware_access_switch": {
        "vendor": "h3c", "os": "comware",
        "name": "🏢 Access Switch",
        "description": "Standard access switch with user VLAN and uplink trunk",
        "data": {
            "system": {"hostname": "SW-ACCESS-01"},
            "vlans": [
                {"vlan": "10", "name": "USERS", "description": "End-user VLAN"},
                {"vlan": "99", "name": "MGMT", "description": "Management"}
            ],
            "interfaces": [
                {"interface": "GigabitEthernet1/0/1", "mode": "access", "vlan": "10", "description": "User Port", "stp_edge": True},
                {"interface": "GigabitEthernet1/0/24", "mode": "trunk", "allowed": "10 99", "description": "Uplink to Core"}
            ]
        }
    },
    "h3c_comware_core_switch": {
        "vendor": "h3c", "os": "comware",
        "name": "🏛️ Core Switch (L3)",
        "description": "Layer 3 core with SVI gateways, OSPF and static routes",
        "data": {
            "system": {"hostname": "SW-CORE-01"},
            "vlans": [
                {"vlan": "10", "name": "USERS", "description": "End-user VLAN"},
                {"vlan": "20", "name": "SERVERS", "description": "Server VLAN"},
                {"vlan": "99", "name": "MGMT", "description": "Management VLAN"}
            ],
            "svis": [
                {"vlan": "10", "description": "User gateway", "ip": "10.10.10.1/24"},
                {"vlan": "20", "description": "Server gateway", "ip": "10.10.20.1/24"},
                {"vlan": "99", "description": "Management", "ip": "10.10.99.1/24"}
            ],
            "interfaces": [
                {"interface": "GigabitEthernet1/0/1", "mode": "trunk", "allowed": "10 20 99", "description": "Downlink"}
            ],
            "static_routes": [
                {"network": "0.0.0.0", "cidr": "0", "next_hop": "10.10.99.254", "description": "Default route"}
            ],
            "ospf": {
                "process_id": "1", "router_id": "10.10.99.1", "area": "0",
                "networks": [{"network": "10.10.0.0", "cidr": "16"}]
            }
        }
    },
    "h3c_comware_trunk": {
        "vendor": "h3c", "os": "comware",
        "name": "🔗 Trunk Uplink",
        "description": "Simple trunk link between switches",
        "data": {
            "interfaces": [
                {"interface": "GigabitEthernet1/0/24", "mode": "trunk", "allowed": "10 20 30 99", "description": "Trunk to SW-CORE"}
            ]
        }
    },
    "h3c_comware_dhcp_on_vlan": {
        "vendor": "h3c", "os": "comware",
        "name": "📡 DHCP on VLAN",
        "description": "VLAN + SVI + DHCP pool — full L3 server setup",
        "data": {
            "vlans": [{"vlan": "10", "name": "USERS", "description": "Office users"}],
            "dhcp_pools": [{
                "pool_name": "USERS_POOL", "network": "10.10.10.0", "cidr": "24",
                "gateway": "10.10.10.1", "dns": "8.8.8.8 1.1.1.1", "lease_days": "7",
                "forbidden_ips": "10.10.10.1 10.10.10.2 10.10.10.3"
            }],
            "svis": [{
                "vlan": "10", "description": "Users gateway", "ip": "10.10.10.1/24",
                "dhcp_mode": "server", "dhcp_apply_pool": "USERS_POOL"
            }]
        }
    },
    "h3c_comware_guest_wifi": {
        "vendor": "h3c", "os": "comware",
        "name": "📶 Guest WiFi VLAN",
        "description": "Isolated guest VLAN with DHCP and ACL",
        "data": {
            "vlans": [{"vlan": "200", "name": "GUEST_WIFI", "description": "Guest isolation"}],
            "dhcp_pools": [{
                "pool_name": "GUEST_POOL", "network": "192.168.200.0", "cidr": "24",
                "gateway": "192.168.200.1", "dns": "8.8.8.8", "lease_days": "1",
                "forbidden_ips": "192.168.200.1"
            }],
            "svis": [{
                "vlan": "200", "description": "Guest WiFi", "ip": "192.168.200.1/24",
                "dhcp_mode": "server", "dhcp_apply_pool": "GUEST_POOL"
            }],
            "acls": [{
                "acl_number": "3000", "description": "Guest-Isolation",
                "rules": [
                    {"rule_id": "5", "action": "deny", "protocol": "ip", "source": "192.168.200.0", "wildcard": "0.0.0.255"},
                    {"rule_id": "10", "action": "permit", "protocol": "ip", "source": "any"}
                ]
            }]
        }
    },
    "h3c_comware_ospf": {
        "vendor": "h3c", "os": "comware",
        "name": "🧭 OSPF Router",
        "description": "OSPF area 0 with multiple networks",
        "data": {
            "system": {"hostname": "RTR-OSPF-01"},
            "ospf": {
                "process_id": "1", "router_id": "1.1.1.1", "area": "0",
                "networks": [
                    {"network": "10.0.0.0", "cidr": "8"},
                    {"network": "192.168.1.0", "cidr": "24"}
                ]
            }
        }
    },
    "h3c_comware_multi_isp_pbr": {
        "vendor": "h3c", "os": "comware",
        "name": "🌐 Multi-ISP PBR (up to 5 ISP)",
        "description": "Policy-based routing with NQA/Track failover across up to 5 ISPs",
        "data": {
            "system": {"hostname": "RT-EDGE-01"},
            "pbr": {
                "mode": "failover", "policy_name": "PBR-ISP", "acl_base": 3100,
                "isps": [
                    {"name": "ISP-A", "gateway": "100.0.0.1", "probe_ip": "8.8.8.8", "wan_interface": "GigabitEthernet0/1", "wan_ip": "100.0.0.2/30", "nat": True},
                    {"name": "ISP-B", "gateway": "200.0.0.1", "probe_ip": "1.1.1.1", "wan_interface": "GigabitEthernet0/2", "wan_ip": "200.0.0.2/30", "nat": True},
                    {"name": "ISP-C", "gateway": "150.0.0.1", "probe_ip": "9.9.9.9", "wan_interface": "GigabitEthernet0/3", "wan_ip": "150.0.0.2/30", "nat": True}
                ],
                "lans": [
                    {"name": "LAN-1", "network": "10.10.10.0", "cidr": "24", "interface": "GigabitEthernet0/0"},
                    {"name": "LAN-2", "network": "10.10.20.0", "cidr": "24", "interface": "GigabitEthernet0/4"}
                ]
            }
        }
    },
    "h3c_comware_dhcp_relay": {
        "vendor": "h3c", "os": "comware",
        "name": "↗️ DHCP Relay",
        "description": "VLAN with DHCP Relay to central server",
        "data": {
            "vlans": [{"vlan": "50", "name": "BRANCH_USERS", "description": "Branch users"}],
            "svis": [{
                "vlan": "50", "description": "Branch gateway", "ip": "172.16.50.1/24",
                "dhcp_mode": "relay", "dhcp_relay": "10.10.100.10"
            }]
        }
    },
    # =========== CISCO IOS ===========
    "cisco_ios_access_switch": {
        "vendor": "cisco", "os": "ios",
        "name": "🏢 Catalyst Access Switch",
        "description": "Cisco Catalyst 2960-style access switch",
        "data": {
            "system": {"hostname": "SW-ACCESS-01"},
            "vlans": [
                {"vlan": "10", "name": "USERS", "description": "End-user VLAN"},
                {"vlan": "99", "name": "MGMT", "description": "Management VLAN"}
            ],
            "interfaces": [
                {"interface": "GigabitEthernet0/1", "mode": "access", "vlan": "10", "description": "User Port", "stp_edge": True},
                {"interface": "GigabitEthernet0/24", "mode": "trunk", "allowed": "10,99", "description": "Uplink"}
            ]
        }
    },
    "cisco_ios_core_router": {
        "vendor": "cisco", "os": "ios",
        "name": "🏛️ ISR Core Router",
        "description": "Cisco ISR with SVI gateways and OSPF",
        "data": {
            "system": {"hostname": "RTR-CORE-01"},
            "vlans": [
                {"vlan": "10", "name": "USERS", "description": "End-user VLAN"},
                {"vlan": "20", "name": "SERVERS", "description": "Server VLAN"}
            ],
            "svis": [
                {"vlan": "10", "description": "Users", "ip": "10.10.10.1/24"},
                {"vlan": "20", "description": "Servers", "ip": "10.10.20.1/24"}
            ],
            "interfaces": [
                {"interface": "GigabitEthernet0/1", "mode": "trunk", "allowed": "10,20", "description": "Downlink"}
            ],
            "ospf": {
                "process_id": "1", "router_id": "1.1.1.1", "area": "0",
                "networks": [{"network": "10.10.0.0", "cidr": "16"}]
            }
        }
    },
    "cisco_ios_dhcp_router": {
        "vendor": "cisco", "os": "ios",
        "name": "📡 DHCP Server Router",
        "description": "Router with DHCP pool for VLAN",
        "data": {
            "vlans": [{"vlan": "10", "name": "USERS", "description": "End-user VLAN"}],
            "dhcp_pools": [{
                "pool_name": "USERS_POOL", "network": "10.10.10.0", "cidr": "24",
                "gateway": "10.10.10.1", "dns": "8.8.8.8 1.1.1.1",
                "domain": "company.local", "lease_days": "7",
                "forbidden_ips": "10.10.10.1 10.10.10.2 10.10.10.3"
            }],
            "svis": [{
                "vlan": "10", "description": "User gateway", "ip": "10.10.10.1/24"
            }]
        }
    },
    "cisco_ios_ospf": {
        "vendor": "cisco", "os": "ios",
        "name": "🧭 OSPF Router",
        "description": "OSPF area 0 setup",
        "data": {
            "system": {"hostname": "RTR-OSPF-01"},
            "ospf": {
                "process_id": "1", "router_id": "1.1.1.1", "area": "0",
                "networks": [
                    {"network": "10.0.0.0", "cidr": "8"},
                    {"network": "192.168.1.0", "cidr": "24"}
                ]
            }
        }
    },
    # =========== CISCO IOS-XE ===========
    "cisco_iosxe_cat9k": {
        "vendor": "cisco", "os": "iosxe",
        "name": "🏢 Catalyst 9000 Switch",
        "description": "Modern Catalyst 9k access switch",
        "data": {
            "system": {"hostname": "C9K-ACCESS-01"},
            "vlans": [
                {"vlan": "10", "name": "USERS", "description": "End-user VLAN"},
                {"vlan": "99", "name": "MGMT", "description": "Management VLAN"}
            ],
            "interfaces": [
                {"interface": "GigabitEthernet1/0/1", "mode": "access", "vlan": "10", "description": "User Port", "stp_edge": True},
                {"interface": "TenGigabitEthernet1/1/1", "mode": "trunk", "allowed": "10,99", "description": "Uplink"}
            ]
        }
    },
    "cisco_iosxe_isr4k": {
        "vendor": "cisco", "os": "iosxe",
        "name": "🏛️ ISR 4000 Router",
        "description": "Modern ISR 4000 with OSPF",
        "data": {
            "system": {"hostname": "ISR4K-01"},
            "vlans": [
                {"vlan": "10", "name": "USERS", "description": "End-user VLAN"},
                {"vlan": "20", "name": "SERVERS", "description": "Server VLAN"}
            ],
            "svis": [
                {"vlan": "10", "description": "Users", "ip": "10.10.10.1/24"},
                {"vlan": "20", "description": "Servers", "ip": "10.10.20.1/24"}
            ],
            "ospf": {
                "process_id": "1", "router_id": "1.1.1.1", "area": "0",
                "networks": [{"network": "10.10.0.0", "cidr": "16"}]
            }
        }
    },
    "cisco_iosxe_dhcp": {
        "vendor": "cisco", "os": "iosxe",
        "name": "📡 DHCP Server",
        "description": "DHCP pool with SVI gateway",
        "data": {
            "vlans": [{"vlan": "10", "name": "USERS", "description": "End-user VLAN"}],
            "dhcp_pools": [{
                "pool_name": "USERS_POOL", "network": "10.10.10.0", "cidr": "24",
                "gateway": "10.10.10.1", "dns": "8.8.8.8 1.1.1.1",
                "domain": "company.local", "lease_days": "7",
                "forbidden_ips": "10.10.10.1 10.10.10.2"
            }],
            "svis": [{"vlan": "10", "description": "User gateway", "ip": "10.10.10.1/24"}]
        }
    },
    # =========== CISCO NX-OS ===========
    "cisco_nxos_leaf": {
        "vendor": "cisco", "os": "nxos",
        "name": "🌱 Nexus 9k Leaf",
        "description": "Nexus leaf switch (access)",
        "data": {
            "system": {"hostname": "N9K-LEAF-01"},
            "vlans": [
                {"vlan": "10", "name": "USERS", "description": "End-user VLAN"},
                {"vlan": "20", "name": "SERVERS", "description": "Server VLAN"}
            ],
            "interfaces": [
                {"interface": "Ethernet1/1", "mode": "access", "vlan": "10", "description": "Server port", "stp_edge": True},
                {"interface": "Ethernet1/49", "mode": "trunk", "allowed": "10,20", "description": "Uplink to spine"}
            ]
        }
    },
    "cisco_nxos_spine": {
        "vendor": "cisco", "os": "nxos",
        "name": "🌲 Nexus 9k Spine (L3)",
        "description": "Nexus spine with SVIs and OSPF",
        "data": {
            "system": {"hostname": "N9K-SPINE-01"},
            "vlans": [
                {"vlan": "10", "name": "USERS", "description": "End-user VLAN"},
                {"vlan": "20", "name": "SERVERS", "description": "Server VLAN"}
            ],
            "svis": [
                {"vlan": "10", "description": "Users", "ip": "10.10.10.1/24"},
                {"vlan": "20", "description": "Servers", "ip": "10.10.20.1/24"}
            ],
            "interfaces": [
                {"interface": "Ethernet1/1", "mode": "trunk", "allowed": "10,20", "description": "To leaf-01"}
            ],
            "ospf": {
                "process_id": "1", "router_id": "1.1.1.1", "area": "0",
                "networks": [{"network": "10.10.0.0", "cidr": "16"}]
            }
        }
    },
    "cisco_nxos_dhcp": {
        "vendor": "cisco", "os": "nxos",
        "name": "📡 Nexus DHCP Server",
        "description": "Nexus with DHCP pool and SVI",
        "data": {
            "vlans": [{"vlan": "10", "name": "USERS", "description": "End-user VLAN"}],
            "dhcp_pools": [{
                "pool_name": "USERS_POOL", "network": "10.10.10.0", "cidr": "24",
                "gateway": "10.10.10.1", "dns": "8.8.8.8 1.1.1.1", "lease_days": "7",
                "forbidden_ips": "10.10.10.1"
            }],
            "svis": [{"vlan": "10", "description": "Users", "ip": "10.10.10.1/24"}]
        }
    }
}

# ============================================================
# ROUTES
# ============================================================
# =========== RUIJIE RGOS ===========
TEMPLATES.update({
    "ruijie_rgos_switch_access": {
        "vendor": "ruijie", "os": "rgos_switch",
        "name": "🏢 Access Switch",
        "description": "User VLAN + management SVI, access ports, trunk uplink, SSH + SNMP",
        "data": {
            "system": {"hostname": "RG-ACCESS-01", "ntp": "time.google.com", "timezone": "WIB 7:00", "admin_user": "admin", "admin_pass": "ChangeMe#2026", "ssh": True, "snmp_community": "CKI-RO", "snmp_location": "Server Room"},
            "vlans": [{"vlan": "10", "name": "USERS"}, {"vlan": "99", "name": "MGMT"}],
            "svis": [{"vlan": "99", "description": "Management", "ip": "10.10.99.11/24"}],
            "interfaces": [
                {"interface": "GigabitEthernet 0/1", "mode": "access", "vlan": "10", "description": "User Port", "stp_edge": True},
                {"interface": "GigabitEthernet 0/2", "mode": "access", "vlan": "10", "description": "User Port", "stp_edge": True},
                {"interface": "GigabitEthernet 0/24", "mode": "trunk", "allowed": "10 99", "pvid": "99", "description": "Uplink to Core"}
            ],
            "static_routes": [{"network": "0.0.0.0", "cidr": "0", "next_hop": "10.10.99.1"}]
        }
    },
    "ruijie_rgos_switch_core": {
        "vendor": "ruijie", "os": "rgos_switch",
        "name": "🏛️ Core Switch (L3)",
        "description": "SVI gateways, DHCP server, OSPF and default route",
        "data": {
            "system": {"hostname": "RG-CORE-01"},
            "vlans": [{"vlan": "10", "name": "USERS"}, {"vlan": "20", "name": "SERVERS"}, {"vlan": "99", "name": "MGMT"}],
            "dhcp_pools": [{"pool_name": "USERS_POOL", "network": "10.10.10.0", "cidr": "24", "gateway": "10.10.10.1", "dns": "8.8.8.8 1.1.1.1", "lease_days": "7", "forbidden_ips": "10.10.10.1 10.10.10.2"}],
            "svis": [
                {"vlan": "10", "description": "User gateway", "ip": "10.10.10.1/24"},
                {"vlan": "20", "description": "Server gateway", "ip": "10.10.20.1/24"},
                {"vlan": "99", "description": "Management", "ip": "10.10.99.1/24"}
            ],
            "interfaces": [{"interface": "GigabitEthernet 0/1", "mode": "trunk", "allowed": "10 20 99", "description": "Downlink to Access"}],
            "static_routes": [{"network": "0.0.0.0", "cidr": "0", "next_hop": "10.10.99.254"}],
            "ospf": {"process_id": "1", "router_id": "10.10.99.1", "area": "0", "networks": [{"network": "10.10.0.0", "cidr": "16"}]}
        }
    },
    "ruijie_rgos_switch_lag": {
        "vendor": "ruijie", "os": "rgos_switch",
        "name": "🔗 LACP Uplink (AggregatePort)",
        "description": "Two ports bundled into AggregatePort 1 as an LACP trunk",
        "data": {
            "vlans": [{"vlan": "10", "name": "USERS"}, {"vlan": "20", "name": "SERVERS"}],
            "interfaces": [
                {"interface": "TenGigabitEthernet 0/25", "mode": "trunk", "allowed": "10 20", "lag": "1", "lag_mode": "active", "description": "LAG member 1"},
                {"interface": "TenGigabitEthernet 0/26", "mode": "trunk", "allowed": "10 20", "lag": "1", "lag_mode": "active", "description": "LAG member 2"}
            ]
        }
    },
    "ruijie_rgos_switch_vrrp": {
        "vendor": "ruijie", "os": "rgos_switch",
        "name": "🛡️ Core Pair (VRRP)",
        "description": "Primary core: SVI with VRRP VIP, priority 120, ACL on the user VLAN",
        "data": {
            "system": {"hostname": "RG-CORE-A"},
            "vlans": [{"vlan": "10", "name": "USERS"}, {"vlan": "20", "name": "SERVERS"}],
            "svis": [
                {"vlan": "10", "description": "Users", "ip": "10.10.10.2/24", "vrrp_id": "10", "vrrp_ip": "10.10.10.1", "vrrp_prio": "120", "acl_in": "100"},
                {"vlan": "20", "description": "Servers", "ip": "10.10.20.2/24", "vrrp_id": "20", "vrrp_ip": "10.10.20.1", "vrrp_prio": "120"}
            ],
            "interfaces": [{"interface": "TenGigabitEthernet 0/25", "mode": "trunk", "allowed": "10 20", "description": "Link to CORE-B"}],
            "acls": [{"acl_number": "100", "description": "Users to servers", "rules": [
                {"action": "permit", "protocol": "tcp", "source": "10.10.10.0", "wildcard": "0.0.0.255", "destination": "10.10.20.0", "dest_wildcard": "0.0.0.255"},
                {"action": "deny", "protocol": "ip", "source": "any"}
            ]}]
        }
    },
    "ruijie_rgos_router_nat": {
        "vendor": "ruijie", "os": "rgos_router",
        "name": "🌐 Internet Router (NAT)",
        "description": "WAN + LAN, NAT overload, DHCP server and default route",
        "data": {
            "system": {"hostname": "RG-EDGE-01", "ntp": "time.google.com", "timezone": "WIB 7:00"},
            "dhcp_pools": [{"pool_name": "LAN_POOL", "network": "192.168.1.0", "cidr": "24", "gateway": "192.168.1.1", "dns": "8.8.8.8 1.1.1.1", "lease_days": "1", "forbidden_ips": "192.168.1.1"}],
            "interfaces": [
                {"interface": "GigabitEthernet 0/0", "mode": "routed", "ip": "203.0.113.2/30", "description": "WAN to ISP", "nat": "outside"},
                {"interface": "GigabitEthernet 0/1", "mode": "routed", "ip": "192.168.1.1/24", "description": "LAN", "nat": "inside"}
            ],
            "static_routes": [{"network": "0.0.0.0", "cidr": "0", "next_hop": "203.0.113.1"}],
            "nat": {"acl_number": "10", "outside": "GigabitEthernet 0/0", "networks": [{"network": "192.168.1.0", "cidr": "24"}]}
        }
    },
    "ruijie_rgos_router_vlans": {
        "vendor": "ruijie", "os": "rgos_router",
        "name": "🔀 Router-on-a-Stick",
        "description": "Dot1Q sub-interfaces per VLAN, DHCP per VLAN, NAT to the internet",
        "data": {
            "system": {"hostname": "RG-ROAS-01"},
            "dhcp_pools": [
                {"pool_name": "STAFF", "network": "192.168.10.0", "cidr": "24", "gateway": "192.168.10.1", "dns": "8.8.8.8", "lease_days": "1", "forbidden_ips": "192.168.10.1"},
                {"pool_name": "GUEST", "network": "192.168.20.0", "cidr": "24", "gateway": "192.168.20.1", "dns": "8.8.8.8", "lease_days": "1", "forbidden_ips": "192.168.20.1"}
            ],
            "interfaces": [
                {"interface": "GigabitEthernet 0/0", "mode": "routed", "ip": "203.0.113.2/30", "description": "WAN", "nat": "outside"},
                {"interface": "GigabitEthernet 0/1", "mode": "routed", "description": "Trunk to switch"},
                {"interface": "GigabitEthernet 0/1.10", "mode": "routed", "dot1q": "10", "ip": "192.168.10.1/24", "description": "STAFF", "nat": "inside"},
                {"interface": "GigabitEthernet 0/1.20", "mode": "routed", "dot1q": "20", "ip": "192.168.20.1/24", "description": "GUEST", "nat": "inside"}
            ],
            "static_routes": [{"network": "0.0.0.0", "cidr": "0", "next_hop": "203.0.113.1"}],
            "nat": {"acl_number": "10", "outside": "GigabitEthernet 0/0", "networks": [{"network": "192.168.10.0", "cidr": "24"}, {"network": "192.168.20.0", "cidr": "24"}]}
        }
    },
    "ruijie_rgos_router_branch": {
        "vendor": "ruijie", "os": "rgos_router",
        "name": "🏬 Branch Router (OSPF)",
        "description": "Branch LAN + WAN link to HQ over OSPF, DHCP relay to HQ server",
        "data": {
            "system": {"hostname": "RG-BRANCH-01"},
            "interfaces": [
                {"interface": "GigabitEthernet 0/0", "mode": "routed", "ip": "10.255.0.2/30", "description": "WAN to HQ"},
                {"interface": "GigabitEthernet 0/1", "mode": "routed", "ip": "172.16.10.1/24", "description": "Branch LAN", "dhcp_relay": "10.10.20.10"}
            ],
            "ospf": {"process_id": "1", "router_id": "172.16.10.1", "area": "0", "networks": [{"network": "10.255.0.0", "cidr": "30"}, {"network": "172.16.10.0", "cidr": "24"}]}
        }
    },
    "ruijie_rgos_wlan_basic": {
        "vendor": "ruijie", "os": "rgos_wlan",
        "name": "📶 AC + Fit AP (1 SSID)",
        "description": "AC with DHCP option 138 for AP discovery and one WPA2-PSK SSID",
        "data": {
            "system": {"hostname": "RG-AC-01"},
            "vlans": [{"vlan": "10", "name": "AP-MGMT"}, {"vlan": "20", "name": "WIFI-USERS"}],
            "dhcp_pools": [
                {"pool_name": "AP_POOL", "network": "10.10.10.0", "cidr": "24", "gateway": "10.10.10.1", "dns": "8.8.8.8", "lease_days": "1", "forbidden_ips": "10.10.10.1", "ac_ip": "10.10.10.1"},
                {"pool_name": "WIFI_POOL", "network": "10.10.20.0", "cidr": "24", "gateway": "10.10.20.1", "dns": "8.8.8.8", "lease_days": "1", "forbidden_ips": "10.10.20.1"}
            ],
            "svis": [
                {"vlan": "10", "description": "AP management", "ip": "10.10.10.1/24"},
                {"vlan": "20", "description": "WiFi users gateway", "ip": "10.10.20.1/24"}
            ],
            "interfaces": [{"interface": "GigabitEthernet 0/1", "mode": "trunk", "allowed": "10 20", "description": "To PoE switch (APs)"}],
            "wlan": {"ac_ip": "10.10.10.1", "ap_group": "default", "ssids": [{"id": "1", "name": "CKI-WiFi", "vlan": "20", "security": "psk", "password": "ChangeMe2026"}]}
        }
    },
    "ruijie_rgos_wlan_guest": {
        "vendor": "ruijie", "os": "rgos_wlan",
        "name": "🎟️ AC + Corp & Guest SSID",
        "description": "Two SSIDs on separate VLANs: staff (WPA2-PSK) and guest, guest VLAN restricted by ACL",
        "data": {
            "system": {"hostname": "RG-AC-02"},
            "vlans": [{"vlan": "10", "name": "AP-MGMT"}, {"vlan": "20", "name": "CORP"}, {"vlan": "30", "name": "GUEST"}],
            "dhcp_pools": [
                {"pool_name": "AP_POOL", "network": "10.10.10.0", "cidr": "24", "gateway": "10.10.10.1", "dns": "8.8.8.8", "lease_days": "1", "forbidden_ips": "10.10.10.1", "ac_ip": "10.10.10.1"},
                {"pool_name": "CORP_POOL", "network": "10.10.20.0", "cidr": "24", "gateway": "10.10.20.1", "dns": "8.8.8.8", "lease_days": "1", "forbidden_ips": "10.10.20.1"},
                {"pool_name": "GUEST_POOL", "network": "10.10.30.0", "cidr": "24", "gateway": "10.10.30.1", "dns": "8.8.8.8 1.1.1.1", "lease_days": "1", "forbidden_ips": "10.10.30.1"}
            ],
            "svis": [
                {"vlan": "10", "description": "AP management", "ip": "10.10.10.1/24"},
                {"vlan": "20", "description": "Corp gateway", "ip": "10.10.20.1/24"},
                {"vlan": "30", "description": "Guest gateway", "ip": "10.10.30.1/24", "acl_in": "101"}
            ],
            "interfaces": [{"interface": "GigabitEthernet 0/1", "mode": "trunk", "allowed": "10 20 30", "description": "To PoE switch (APs)"}],
            "acls": [{"acl_number": "101", "description": "Guest: internet only", "rules": [
                {"action": "deny", "protocol": "ip", "source": "10.10.30.0", "wildcard": "0.0.0.255", "destination": "10.10.0.0", "dest_wildcard": "0.0.255.255"},
                {"action": "permit", "protocol": "ip", "source": "any"}
            ]}],
            "wlan": {"ac_ip": "10.10.10.1", "ap_group": "default", "ssids": [
                {"id": "1", "name": "CKI-Corp", "vlan": "20", "security": "psk", "password": "ChangeMe2026"},
                {"id": "2", "name": "CKI-Guest", "vlan": "30", "security": "psk", "password": "Welcome2026"}
            ]}
        }
    },
})

@app.errorhandler(413)
def _too_big(e):
    return jsonify({'success': False, 'error': 'Request too large (max 2 MB)'}), 413


@app.route("/")
def root():
    return jsonify({
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "vendors": list(VENDORS.keys()),
        "docs": "https://configlabs.online"
    })

@app.route("/api/health", methods=["GET"])
def api_health():
    try:
        db.session.execute(db.text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({"status": "ok", "db": db_ok, "version": APP_VERSION}), 200

@app.route("/vendors", methods=["GET"])
def vendors():
    return jsonify(VENDORS)

@app.route("/generate", methods=["POST"])
def generate():
    try:
        payload = request.json or {}
        vendor = payload.get("vendor", "h3c")
        os_id = payload.get("os", "comware")
        data = payload.get("data", payload)  # fall back: treat body as data (v1 compat)
        # Back-compat: v1 didn't have vendor/os envelope
        if "data" not in payload and ("vlans" in payload or "svis" in payload or "interfaces" in payload):
            data = payload
            vendor = "h3c"
            os_id = "comware"
        result = generate_config(vendor, os_id, data)
        return jsonify({
            "config": result,
            "lines": len(result.split("\n")),
            "vendor": vendor,
            "os": os_id,
            "success": True
        })
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 400

@app.route("/templates", methods=["GET"])
def templates():
    vendor = request.args.get("vendor")
    os_id = request.args.get("os")
    if vendor and os_id:
        filtered = {k: v for k, v in TEMPLATES.items() if v.get("vendor") == vendor and v.get("os") == os_id}
        return jsonify(filtered)
    elif vendor:
        filtered = {k: v for k, v in TEMPLATES.items() if v.get("vendor") == vendor}
        return jsonify(filtered)
    return jsonify(TEMPLATES)


# ==========================================================
# CONFIG TRANSLATOR API (free tier limits enforced here, on the server)
# ==========================================================
TR_FREE_DAILY = 3
TR_FREE_LINES = 150
TR_PRO_LINES = 5000

def _wib_today():
    return (datetime.utcnow() + timedelta(hours=7)).date()

def _tr_identity():
    """-> (key, email). Logged-in users are counted by account, everyone else by a salted hash of the IP."""
    import hashlib
    raw = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    u = decode_token(raw) if raw else None
    if u and u.get("user_id"):
        return "u" + str(u["user_id"]), str(u.get("email") or "").lower()
    ip = (request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.remote_addr or "?").strip()
    return "i" + hashlib.sha256((ip + "|" + str(app.config["SECRET_KEY"])).encode()).hexdigest()[:40], ""

def _tr_is_pro(email):
    pro = {e.strip().lower() for e in os.environ.get("PRO_EMAILS", "").split(",") if e.strip()}
    return bool(email) and email in pro

def _tr_used(key):
    row = TranslateUse.query.filter_by(day=_wib_today(), key=key).first()
    return row.count if row else 0

def _tr_bump(key, cap=None):
    """Add one use. With cap: refuse (return False) when the cap is already reached."""
    from sqlalchemy.exc import IntegrityError
    for _ in range(2):
        row = TranslateUse.query.filter_by(day=_wib_today(), key=key).first()
        if row is None:
            db.session.add(TranslateUse(day=_wib_today(), key=key, count=1))
        else:
            if cap is not None and row.count >= cap: return False
            row.count += 1
        try:
            db.session.commit(); return True
        except IntegrityError:
            db.session.rollback()
    return False

def _tr_limits(key, email):
    pro = _tr_is_pro(email)
    used = _tr_used(key)
    return {"plan": "pro" if pro else "free", "used": used, "daily_limit": None if pro else TR_FREE_DAILY,
            "remaining": None if pro else max(TR_FREE_DAILY - used, 0), "lines_limit": TR_PRO_LINES if pro else TR_FREE_LINES, "resets": "00:00 WIB"}

@app.route("/api/translate/limits", methods=["GET"])
def api_translate_limits():
    key, email = _tr_identity()
    return jsonify(_tr_limits(key, email))

@app.route("/api/translate", methods=["POST"])
def api_translate():
    key, email = _tr_identity()
    try:
        payload = request.get_json(silent=True) or {}
        source = payload.get("source")
        if source not in ("cisco", "ruijie"):
            return jsonify({"success": False, "error": "Pick a source: Cisco or Ruijie"}), 400
        text = str(payload.get("config") or "")
        lines = [l for l in text.replace("\r", "").split("\n") if l.strip() and not l.strip().startswith("!")]
        lim = _tr_limits(key, email)
        if not lines:
            return jsonify({"success": False, "error": "Paste a config first"}), 400
        if len(lines) > lim["lines_limit"]:
            return jsonify({"success": False, "code": "limit_lines", "limits": lim,
                            "error": f"This config has {len(lines)} lines. The free plan translates up to {lim['lines_limit']} lines at a time."}), 413
        opts = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        if lim["plan"] == "free":
            if not _tr_bump(key, TR_FREE_DAILY):
                return jsonify({"success": False, "code": "limit_daily", "limits": _tr_limits(key, email),
                                "error": f"Daily limit reached ({TR_FREE_DAILY} translations). It resets at 00:00 WIB."}), 429
        try:
            cfg, rep, _data = translate_config(source, text, opts.get("member", 1), str(opts.get("device", "auto")))
        except Exception:
            if lim["plan"] == "free":   # give the use back when the translator itself failed
                row = TranslateUse.query.filter_by(day=_wib_today(), key=key).first()
                if row and row.count > 0: row.count -= 1; db.session.commit()
            raise
        if lim["plan"] == "pro": _tr_bump(key)
        return jsonify({"success": True, "config": cfg, "report": rep, "lines": len(cfg.split("\n")), "limits": _tr_limits(key, email),
                        "source": source, "target": "h3c_comware"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": "Could not translate this config (" + type(e).__name__ + ")"}), 400

@app.route("/api/pro-waitlist", methods=["POST"])
def api_pro_waitlist():
    key, _ = _tr_identity()
    email = str((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
    if not re.match(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,20}$", email) or len(email) > 254:
        return jsonify({"success": False, "error": "Enter a valid email"}), 400
    if not _tr_bump("w" + key[:40], 5):
        return jsonify({"success": False, "error": "Too many tries today"}), 429
    try:
        if not ProWaitlist.query.filter_by(email=email).first():
            db.session.add(ProWaitlist(email=email)); db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({"success": True, "message": "You are on the list. We will email you when Pro opens."})

@app.route("/feedback", methods=["POST"])
def feedback():
    try:
        data = request.json or {}
        _clean = lambda v, n: re.sub(r"[\r\n\t\x00-\x1f]+", " ", str(v or ""))[:n]
        msg = _clean(data.get("message", ""), 300)
        email = _clean(data.get("email", "anonymous"), 100)
        print(f"[FEEDBACK v{APP_VERSION}] from={email} msg={msg}")
        return jsonify({"success": True, "message": "Thanks for your feedback!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

# ============================================================
# SAVED FILES API
# ============================================================

@app.route('/api/files', methods=['GET'])
def api_get_files():
    """Get all saved files for current user"""
    raw   = request.headers.get('Authorization', '')
    token = raw.replace('Bearer ', '').strip()
    data  = decode_token(token)
    if not data:
        return jsonify({'error': 'Unauthorized'}), 401

    file_type = request.args.get('type')   # optional filter (only 'config' exists now)
    query = SavedFile.query.filter_by(user_id=data['user_id']).filter(SavedFile.file_type.notin_(['topology', 'wifi_matlib', 'wifi_apcat']))  # legacy / internal rows hidden
    if file_type:
        query = query.filter_by(file_type=file_type)
    files = query.order_by(SavedFile.updated_at.desc()).all()
    return jsonify([f.to_dict() for f in files])

@app.route('/api/files', methods=['POST'])
def api_save_file():
    """Save a new file (config)"""
    raw   = request.headers.get('Authorization', '')
    token = raw.replace('Bearer ', '').strip()
    data  = decode_token(token)
    if not data:
        return jsonify({'error': 'Unauthorized'}), 401

    body = request.json
    if not body or not body.get('name') or not body.get('file_type') or not body.get('data'):
        return jsonify({'error': 'Missing required fields: name, file_type, data'}), 400

    if body['file_type'] != 'config':
        return jsonify({'error': 'Unsupported file_type'}), 400

    import json as _json
    saved = SavedFile(
        user_id      = data['user_id'],
        name         = body['name'],
        file_type    = body['file_type'],
        data         = _json.dumps(body['data']),
        vendor       = body.get('vendor'),
        hostname     = body.get('hostname'),
        device_count = body.get('device_count'),
    )
    db.session.add(saved)
    db.session.commit()
    return jsonify({'id': saved.id, 'message': 'Saved!'}), 201

@app.route('/api/files/<int:file_id>', methods=['GET'])
def api_get_file(file_id):
    """Load a specific saved file"""
    raw   = request.headers.get('Authorization', '')
    token = raw.replace('Bearer ', '').strip()
    data  = decode_token(token)
    if not data:
        return jsonify({'error': 'Unauthorized'}), 401

    saved = SavedFile.query.filter_by(id=file_id, user_id=data['user_id']).first()
    if not saved:
        return jsonify({'error': 'File not found'}), 404
    return jsonify(saved.to_dict_full())

@app.route('/api/files/<int:file_id>', methods=['PUT'])
def api_update_file(file_id):
    """Update (overwrite) an existing saved file"""
    raw   = request.headers.get('Authorization', '')
    token = raw.replace('Bearer ', '').strip()
    data  = decode_token(token)
    if not data:
        return jsonify({'error': 'Unauthorized'}), 401

    saved = SavedFile.query.filter_by(id=file_id, user_id=data['user_id']).first()
    if not saved:
        return jsonify({'error': 'File not found'}), 404

    body = request.json
    import json as _json
    if body.get('name'):         saved.name         = body['name']
    if body.get('data'):         saved.data         = _json.dumps(body['data'])
    if body.get('vendor'):       saved.vendor       = body['vendor']
    if body.get('hostname'):     saved.hostname     = body['hostname']
    if body.get('device_count'): saved.device_count = body['device_count']
    saved.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Updated!'})

@app.route('/api/files/<int:file_id>', methods=['DELETE'])
def api_delete_file(file_id):
    """Delete a saved file"""
    raw   = request.headers.get('Authorization', '')
    token = raw.replace('Bearer ', '').strip()
    data  = decode_token(token)
    if not data:
        return jsonify({'error': 'Unauthorized'}), 401

    saved = SavedFile.query.filter_by(id=file_id, user_id=data['user_id']).first()
    if not saved:
        return jsonify({'error': 'File not found'}), 404

    db.session.delete(saved)
    db.session.commit()
    return jsonify({'message': 'Deleted'})

# ============================================================
# AUTH — Google OAuth
# ============================================================

@app.route('/auth/google')
def auth_google():
    """Redirect user to Google login page"""
    redirect_uri = 'https://configlabs.online/auth/google/callback'
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def auth_google_callback():
    """Google sends user back here after they log in"""
    try:
        token     = google.authorize_access_token()
        user_info = token.get('userinfo')

        # Find existing user or create new one
        user = User.query.filter_by(email=user_info['email']).first()
        if not user:
            user = User(
                email       = user_info['email'],
                name        = user_info.get('name', 'User'),
                avatar_url  = user_info.get('picture'),
                provider    = 'google',
                provider_id = user_info.get('sub'),
            )
            db.session.add(user)

        user.last_login = datetime.utcnow()
        db.session.commit()

        jwt_token = create_token(user)
        # Redirect back to frontend with token in URL (JS grabs it)
        return redirect(f'/?auth_token={jwt_token}')

    except Exception as e:
        print(f"[AUTH ERROR] Google callback: {e}")
        return redirect(f'/?auth_error=Login+failed')

# ── WiFi Planner: per-account default wall library ───────────
WIFI_MATLIB = 'wifi_matlib'
_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')

def _clean_matlib(arr):
    """Validate/normalise a wall library; returns a clean list or None."""
    if not isinstance(arr, list) or not 1 <= len(arr) <= 40:
        return None
    out, seen = [], set()
    for m in arr:
        if not isinstance(m, dict):
            return None
        mid = str(m.get('id', ''))[:40]
        if not mid or mid in seen:
            return None
        seen.add(mid)
        b = m.get('b') or {}
        try:
            bb = {k: max(0.0, min(80.0, float(b[k]))) for k in ('2.4', '5', '6')}
            thick = max(0.0, min(500.0, float(m.get('thick', 10))))
        except (KeyError, TypeError, ValueError):
            return None
        color = m.get('color') if isinstance(m.get('color'), str) and _HEX.match(m.get('color')) else '#909090'
        out.append({'id': mid, 'name': (str(m.get('name') or 'Material')[:60]), 'color': color, 'thick': thick, 'b': bb, 'attn': bb['5']})
    return out

def _wifi_user():
    raw  = request.headers.get('Authorization', '')
    data = decode_token(raw.replace('Bearer ', '').strip())
    return data['user_id'] if data else None

@app.route('/api/wifi/matlib', methods=['GET'])
def api_wifi_matlib_get():
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    row = SavedFile.query.filter_by(user_id=uid, file_type=WIFI_MATLIB).first()
    if not row:
        return jsonify({'mats': None})
    try:
        return jsonify({'mats': json.loads(row.data), 'updated_at': row.updated_at.isoformat()})
    except Exception:
        return jsonify({'mats': None})

@app.route('/api/wifi/matlib', methods=['PUT'])
def api_wifi_matlib_put():
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    mats = _clean_matlib((request.get_json(silent=True) or {}).get('mats'))
    if mats is None:
        return jsonify({'error': 'Invalid wall library'}), 400
    row = SavedFile.query.filter_by(user_id=uid, file_type=WIFI_MATLIB).first()
    if row:
        row.data = json.dumps(mats)
    else:
        row = SavedFile(user_id=uid, name='WiFi wall library', file_type=WIFI_MATLIB, data=json.dumps(mats))
        db.session.add(row)
    db.session.commit()
    return jsonify({'mats': mats, 'message': 'Saved'})

# ── WiFi Planner: per-account AP catalog (edited specs + own models) ──
WIFI_APCAT = 'wifi_apcat'

def _clean_apcat(c):
    if not isinstance(c, dict):
        return None
    def num(v, lo, hi):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return None
    out = {'ovr': {}, 'custom': []}
    ovr = c.get('ovr') if isinstance(c.get('ovr'), dict) else {}
    for k, o in list(ovr.items())[:200]:
        if not isinstance(k, str) or '|' not in k or len(k) > 60 or not isinstance(o, dict):
            continue
        r = {}
        for f, lo, hi in (('tx', 0, 36), ('gain', 0, 20), ('w', 0, 300)):
            v = num(o.get(f), lo, hi)
            if v is not None:
                r[f] = v
        if isinstance(o.get('poe'), str):
            r['poe'] = o['poe'][:16]
        if r:
            out['ovr'][k] = r
    for m in (c.get('custom') if isinstance(c.get('custom'), list) else [])[:30]:
        if not isinstance(m, dict):
            continue
        bands = [b for b in ('2.4', '5', '6') if b in (m.get('bands') or [])]
        if not bands:
            continue
        wf = int(m.get('wifi')) if str(m.get('wifi')) in ('5', '6', '7') else 6
        out['custom'].append({
            'id': re.sub(r'[^A-Za-z0-9_-]', '', str(m.get('id') or ''))[:30] or 'c%d' % len(out['custom']),
            'name': str(m.get('name') or 'My AP')[:40], 'wifi': wf, 'bands': bands,
            'tx': num(m.get('tx'), 0, 36) if num(m.get('tx'), 0, 36) is not None else 20,
            'gain': num(m.get('gain'), 0, 20) if num(m.get('gain'), 0, 20) is not None else 3,
            'w': num(m.get('w'), 0, 300) or 0, 'poe': str(m.get('poe') or '')[:16]})
    return out

@app.route('/api/wifi/apcat', methods=['GET'])
def api_wifi_apcat_get():
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    row = SavedFile.query.filter_by(user_id=uid, file_type=WIFI_APCAT).first()
    if not row:
        return jsonify({'cat': None})
    try:
        return jsonify({'cat': json.loads(row.data), 'updated_at': row.updated_at.isoformat()})
    except Exception:
        return jsonify({'cat': None})

@app.route('/api/wifi/apcat', methods=['PUT'])
def api_wifi_apcat_put():
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    cat = _clean_apcat((request.get_json(silent=True) or {}).get('cat'))
    if cat is None:
        return jsonify({'error': 'Invalid AP catalog'}), 400
    row = SavedFile.query.filter_by(user_id=uid, file_type=WIFI_APCAT).first()
    if row:
        row.data = json.dumps(cat)
    else:
        db.session.add(SavedFile(user_id=uid, name='WiFi AP catalog', file_type=WIFI_APCAT, data=json.dumps(cat)))
    db.session.commit()
    return jsonify({'cat': cat, 'message': 'Saved'})

# ── WiFi Planner: projects saved to the account + read-only share links ──
_ID = re.compile(r'^[A-Za-z0-9_-]{3,40}$')
MAX_PROJ_BYTES = 1_500_000
MAX_PLAN_BYTES = 3_500_000

def _proj_summary(row):
    try:
        d = json.loads(row.data)
    except Exception:
        d = {}
    floors = d.get('floors') or []
    aps = sum(len(((f.get('data') or {}).get('aps')) or []) for f in floors)
    return {'id': row.id, 'name': row.name, 'client': d.get('client', ''), 'location': d.get('location', ''),
            'floors': len(floors), 'aps': aps, 'updated_at': row.updated_at.isoformat(), 'shared': bool(row.share_token)}

def _own_project(pid, uid):
    row = WifiProject.query.get(pid)
    if not row:
        return None, (jsonify({'error': 'Not found'}), 404)
    if row.user_id != uid:
        return None, (jsonify({'error': 'Forbidden'}), 403)
    return row, None

@app.route('/api/wifi/projects', methods=['GET'])
def api_wifi_projects():
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    rows = WifiProject.query.filter_by(user_id=uid).order_by(WifiProject.updated_at.desc()).all()
    return jsonify([_proj_summary(r) for r in rows])

@app.route('/api/wifi/projects/<pid>', methods=['GET'])
def api_wifi_project_get(pid):
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    row, err = _own_project(pid, uid)
    if err:
        return err
    return jsonify({'project': json.loads(row.data), 'updated_at': row.updated_at.isoformat(), 'share_token': row.share_token,
                    'plans': [p.floor_id for p in WifiPlan.query.filter_by(project_id=pid).all()]})

@app.route('/api/wifi/projects/<pid>', methods=['PUT'])
def api_wifi_project_put(pid):
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    if not _ID.match(pid):
        return jsonify({'error': 'Bad id'}), 400
    body = request.get_json(silent=True) or {}
    proj = body.get('project')
    if not isinstance(proj, dict) or not isinstance(proj.get('floors'), list) or not proj['floors']:
        return jsonify({'error': 'Invalid project'}), 400
    raw = json.dumps(proj)
    if len(raw) > MAX_PROJ_BYTES:
        return jsonify({'error': 'Project too large'}), 413
    name = str(proj.get('name') or 'Untitled')[:255]
    row = WifiProject.query.get(pid)
    if row and row.user_id != uid:
        return jsonify({'error': 'Forbidden'}), 403
    if row:
        base = body.get('base')
        if base and base != row.updated_at.isoformat() and not body.get('force'):
            return jsonify({'error': 'Newer version in your account', 'updated_at': row.updated_at.isoformat()}), 409
        row.name, row.data, row.updated_at = name, raw, datetime.utcnow()
    else:
        if WifiProject.query.filter_by(user_id=uid).count() >= 200:
            return jsonify({'error': 'Project limit reached'}), 400
        row = WifiProject(id=pid, user_id=uid, name=name, data=raw)
        db.session.add(row)
    db.session.commit()
    return jsonify({'updated_at': row.updated_at.isoformat(), 'share_token': row.share_token})

@app.route('/api/wifi/projects/<pid>', methods=['DELETE'])
def api_wifi_project_del(pid):
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    row, err = _own_project(pid, uid)
    if err:
        return err
    WifiPlan.query.filter_by(project_id=pid).delete()
    db.session.delete(row)
    db.session.commit()
    return jsonify({'message': 'Deleted'})

@app.route('/api/wifi/projects/<pid>/plan/<fid>', methods=['PUT'])
def api_wifi_plan_put(pid, fid):
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    row, err = _own_project(pid, uid)
    if err:
        return err
    if not _ID.match(fid):
        return jsonify({'error': 'Bad id'}), 400
    data = (request.get_json(silent=True) or {}).get('data')
    if not isinstance(data, str) or not data.startswith('data:image/') or len(data) > MAX_PLAN_BYTES:
        return jsonify({'error': 'Invalid or too large image'}), 400
    pl = WifiPlan.query.filter_by(project_id=pid, floor_id=fid).first()
    if pl:
        pl.data = data
    else:
        db.session.add(WifiPlan(project_id=pid, floor_id=fid, data=data))
    db.session.commit()
    return jsonify({'message': 'Saved'})

@app.route('/api/wifi/projects/<pid>/plan/<fid>', methods=['GET'])
def api_wifi_plan_get(pid, fid):
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    row, err = _own_project(pid, uid)
    if err:
        return err
    pl = WifiPlan.query.filter_by(project_id=pid, floor_id=fid).first()
    return jsonify({'data': pl.data if pl else None})

@app.route('/api/wifi/projects/<pid>/plan/<fid>', methods=['DELETE'])
def api_wifi_plan_del(pid, fid):
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    row, err = _own_project(pid, uid)
    if err:
        return err
    WifiPlan.query.filter_by(project_id=pid, floor_id=fid).delete()
    db.session.commit()
    return jsonify({'message': 'Deleted'})

@app.route('/api/wifi/projects/<pid>/share', methods=['POST', 'DELETE'])
def api_wifi_share(pid):
    uid = _wifi_user()
    if not uid:
        return jsonify({'error': 'Unauthorized'}), 401
    row, err = _own_project(pid, uid)
    if err:
        return err
    if request.method == 'POST':
        if not row.share_token:
            import secrets as _s
            row.share_token = _s.token_urlsafe(18)
    else:
        row.share_token = None
    db.session.commit()
    return jsonify({'share_token': row.share_token})

@app.route('/api/wifi/shared/<token>', methods=['GET'])
def api_wifi_shared(token):
    row = WifiProject.query.filter_by(share_token=token).first() if token else None
    if not row:
        return jsonify({'error': 'This link is not valid anymore'}), 404
    proj = json.loads(row.data)
    proj.pop('notes', None)   # internal notes are not part of the shared view
    return jsonify({'project': proj, 'plans': [p.floor_id for p in WifiPlan.query.filter_by(project_id=row.id).all()], 'updated_at': row.updated_at.isoformat()})

@app.route('/api/wifi/shared/<token>/plan/<fid>', methods=['GET'])
def api_wifi_shared_plan(token, fid):
    row = WifiProject.query.filter_by(share_token=token).first() if token else None
    if not row:
        return jsonify({'error': 'Not found'}), 404
    pl = WifiPlan.query.filter_by(project_id=row.id, floor_id=fid).first()
    return jsonify({'data': pl.data if pl else None})

# ── Current user ─────────────────────────────────────────────

@app.route('/api/me', methods=['GET'])
def api_me():
    """Return current user based on JWT token"""
    raw   = request.headers.get('Authorization', '')
    token = raw.replace('Bearer ', '').strip()
    data  = decode_token(token)
    if not data:
        return jsonify({'error': 'Not logged in'}), 401

    user = User.query.get(data['user_id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404

    return jsonify(user.to_dict())

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """Logout is handled client-side (just deletes token from localStorage)"""
    return jsonify({'message': 'Logged out'}), 200

# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
