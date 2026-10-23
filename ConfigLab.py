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
from models import db, User, SavedFile, WifiProject, WifiPlan
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
APP_VERSION = "7.6.0"

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
        for ip in _fb: config.append(f"dhcp server forbidden-ip {ip}")
        if _fb: config.append("#")
        for p in pools:
            if not p.get("pool_name"): continue
            config.append(f"dhcp server ip-pool {p['pool_name']}")
            if p.get("gateway"): config.append(f" gateway-list {p['gateway']}")
            if p.get("network") and p.get("cidr"):
                config.append(f" network {p['network']} mask {cidr_to_mask(p['cidr'])}")
            if p.get("dns"): config.append(f" dns-list {p['dns']}")
            if p.get("lease_days"): config.append(f" expired day {p['lease_days']}")
            if p.get("domain"): config.append(f" domain-name {p['domain']}")
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
            pass  # common pools are matched to the interface subnet automatically (dhcp select server global-pool is the default)
        elif dhcp_mode == "relay" and s.get("dhcp_relay"):
            config.append(" dhcp select relay")
            config.append(f" dhcp relay server-address {s['dhcp_relay']}")
        if s.get("shutdown"): config.append(" shutdown")
        config.append("#")

    # Physical interfaces
    for i in data.get("interfaces", []):
        if not i.get("interface"): continue
        config.append(f"interface {i['interface']}")
        if i.get("description"): config.append(f" description {i['description']}")
        mode = i.get("mode", "access")
        if mode == "access":
            config.append(" port link-type access")
            if i.get("vlan"): config.append(f" port access vlan {i['vlan']}")
        elif mode == "trunk":
            config.append(" port link-type trunk")
            config.append(" undo port trunk permit vlan 1")
            if i.get("allowed"): config.append(f" port trunk permit vlan {' '.join(str(i['allowed']).replace(',', ' ').split())}")
            if i.get("pvid"): config.append(f" port trunk pvid vlan {i['pvid']}")
        elif mode == "hybrid":
            config.append(" port link-type hybrid")
            config.append(" undo port hybrid vlan 1")
            if i.get("untagged"): config.append(f" port hybrid vlan {i['untagged']} untagged")
            if i.get("tagged"): config.append(f" port hybrid vlan {i['tagged']} tagged")
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
        if ospf.get("area") not in (None, ""):
            config.append(f" area {format_area(ospf['area'])}")
            for net in ospf.get("networks", []):
                if net.get("network") and net.get("cidr"):
                    config.append(f"  network {net['network']} {cidr_to_wildcard(net['cidr'])}")
        config.append("#")

    # ACLs
    for a in data.get("acls", []):
        num = a.get("acl_number")
        if not num: continue
        try: n = int(num)
        except: continue
        acl_type = "basic" if 2000 <= n <= 2999 else "advanced"
        config.append(f"acl {acl_type} {n}")
        if a.get("description"): config.append(f" description {a['description']}")
        _auto = 0
        for rule in a.get("rules", []):
            if not (rule.get("action") and rule.get("source")): continue
            _auto += 5
            rid = (rule.get("rule_id") or "").strip() or str(_auto)
            proto = rule.get("protocol", "ip")
            src = rule["source"]
            if src.lower() == "any":
                line = f" rule {rid} {rule['action']} {proto} source any"
            else:
                wc = rule.get("wildcard") or "0"
                line = f" rule {rid} {rule['action']} {proto} source {src} {wc}"
            dst = (rule.get("destination") or "").strip()
            if dst and dst.lower() != "any" and acl_type == "advanced":
                line += f" destination {dst} {rule.get('dest_wildcard') or '0'}"
            config.append(" " + " ".join(line.split()).lstrip())
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
