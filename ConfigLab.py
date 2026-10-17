"""
╔══════════════════════════════════════════════════════════════╗
║  ConfigLabs v2.0 — Multi-Vendor Network Config Generator    ║
║                                                              ║
║  Supported vendors:                                          ║
║    🟢 H3C Comware v7                                         ║
║    🔵 Cisco IOS (Catalyst 2960/3750, ISR)                   ║
║    🔵 Cisco IOS-XE (Catalyst 9000, modern ISR)              ║
║    🔵 Cisco NX-OS (Nexus switches)                          ║
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
APP_VERSION = "6.1.0"

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
            config.append(f" sysname {sys_data['hostname']}")
            config.append("#")
        if sys_data.get("timezone"):
            config.append(f" clock timezone {sys_data['timezone']}")
            config.append("#")
        if sys_data.get("ntp"):
            config.append(f" ntp-service unicast-server {sys_data['ntp']}")
            config.append("#")
        if sys_data.get("banner"):
            config.append(f" header shell {sys_data['banner']}")
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
        config.append(" dhcp enable")
        config.append("#")
        for p in pools:
            if not p.get("pool_name"): continue
            config.append(f"dhcp server ip-pool {p['pool_name']}")
            if p.get("gateway"): config.append(f" gateway-list {p['gateway']}")
            if p.get("network") and p.get("cidr"):
                config.append(f" network {p['network']} mask {cidr_to_mask(p['cidr'])}")
            if p.get("dns"): config.append(f" dns-list {p['dns']}")
            if p.get("lease_days"): config.append(f" expired day {p['lease_days']}")
            if p.get("domain"): config.append(f" domain-name {p['domain']}")
            forbidden = p.get("forbidden_ips", "")
            if forbidden:
                for ip in str(forbidden).replace(",", " ").split():
                    if ip.strip(): config.append(f" forbidden-ip {ip.strip()}")
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
        if dhcp_mode == "server" and s.get("dhcp_apply_pool"):
            config.append(f" dhcp server apply ip-pool {s['dhcp_apply_pool']}")
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
            if i.get("allowed"): config.append(f" port trunk permit vlan {i['allowed']}")
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
        for rule in a.get("rules", []):
            if not (rule.get("action") and rule.get("source")): continue
            rid = rule.get("rule_id", "").strip()
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
                {"vlan": "10", "name": "USERS"},
                {"vlan": "20", "name": "SERVERS"},
                {"vlan": "99", "name": "MGMT"}
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
                {"vlan": "10", "name": "USERS"},
                {"vlan": "99", "name": "MGMT"}
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
                {"vlan": "10", "name": "USERS"},
                {"vlan": "20", "name": "SERVERS"}
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
            "vlans": [{"vlan": "10", "name": "USERS"}],
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
                {"vlan": "10", "name": "USERS"},
                {"vlan": "99", "name": "MGMT"}
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
                {"vlan": "10", "name": "USERS"},
                {"vlan": "20", "name": "SERVERS"}
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
            "vlans": [{"vlan": "10", "name": "USERS"}],
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
                {"vlan": "10", "name": "USERS"},
                {"vlan": "20", "name": "SERVERS"}
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
                {"vlan": "10", "name": "USERS"},
                {"vlan": "20", "name": "SERVERS"}
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
            "vlans": [{"vlan": "10", "name": "USERS"}],
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
        msg = data.get("message", "")
        email = data.get("email", "anonymous")
        print(f"[FEEDBACK v{APP_VERSION}] from={email} msg={msg[:300]}")
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
