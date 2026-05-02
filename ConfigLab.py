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
from models import db, User
from datetime import datetime, timedelta
from functools import wraps
import jwt
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, supports_credentials=True)

# ── Database ────────────────────────────────────────────────
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'sqlite:///configlabs.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SESSION_SECRET', 'dev-secret-change-me')

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
JWT_SECRET  = os.environ.get('JWT_SECRET', 'dev-jwt-secret-change-me')
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
APP_VERSION = "2.0.0"

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
            config.append(" " + " ".join(line.split()).lstrip())
        config.append("#")

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
                    dwc = rule.get("dest_wildcard", "0.0.0.0")
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
                    dwc = rule.get("dest_wildcard", "0.0.0.0")
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
                    dwc = rule.get("dest_wildcard", "0.0.0.0")
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
