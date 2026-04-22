"""
ConfigLabs — Multi-vendor Network Config Generator
Version 1.1.0 — Week 1 Fixes (Real H3C Syntax Compliance)

What's new in v1.1:
-------------------
[FIX] DHCP server apply on VLAN interfaces (links pool to SVI)
[FIX] Replaced 'quit' with '#' as block separator (real H3C format)
[FIX] Fixed 'Vlan-interface X' → 'Vlan-interfaceX' (no space)
[FIX] Added 'undo port trunk permit vlan 1' on all trunks (security)
[FIX] ACL: 'acl advanced N' / 'acl basic N' + 'permit ip' + wildcard mask
[FIX] OSPF router-id on same line as 'ospf X' (real config style)
[FIX] DHCP multiple forbidden-ip entries supported
[NEW] Split architecture: VLANs (L2) and VLAN-interfaces (L3 SVI) separate
[NEW] DHCP modes on SVI: none / server / relay / client
[NEW] Feedback endpoint
[NEW] SEO-friendly root response
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)

APP_NAME = "ConfigLabs"
APP_VERSION = "1.1.0"
CURRENT_VENDOR = "h3c"
SUPPORTED_VENDORS = {
    "h3c": {"name": "H3C", "os": "Comware v7", "status": "available"},
    "cisco": {"name": "Cisco", "os": "IOS / NX-OS", "status": "coming_soon"},
    "huawei": {"name": "Huawei", "os": "VRP", "status": "coming_soon"},
    "juniper": {"name": "Juniper", "os": "Junos", "status": "coming_soon"},
    "arista": {"name": "Arista", "os": "EOS", "status": "coming_soon"},
    "mikrotik": {"name": "MikroTik", "os": "RouterOS", "status": "coming_soon"},
}

# ==========================================================
# HELPERS
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
    """Format OSPF area as 0.0.0.0 dotted format"""
    area = str(area).strip()
    if not area:
        return "0.0.0.0"
    if "." in area:
        return area
    try:
        n = int(area)
        return f"{(n >> 24) & 0xff}.{(n >> 16) & 0xff}.{(n >> 8) & 0xff}.{n & 0xff}"
    except:
        return area

# ==========================================================
# GENERATORS (H3C Comware v7 — real device syntax)
# ==========================================================
def gen_system_block(system):
    out = []
    if not system: return out
    if system.get("hostname"):
        out.append(f" sysname {system['hostname']}")
        out.append("#")
    if system.get("timezone"):
        out.append(f" clock timezone {system['timezone']}")
        out.append("#")
    if system.get("ntp"):
        out.append(f" ntp-service unicast-server {system['ntp']}")
        out.append("#")
    if system.get("banner"):
        out.append(f" header shell {system['banner']}")
        out.append("#")
    return out

def gen_vlan_block(vlans):
    """Pure L2 VLAN creation — no IP"""
    out = []
    for v in vlans:
        if not v.get("vlan"): continue
        out.append(f"vlan {v['vlan']}")
        if v.get("name"):
            out.append(f" name {v['name']}")
        if v.get("description"):
            out.append(f" description {v['description']}")
        out.append("#")
    return out

def gen_svi_block(svis):
    """
    Layer 3 VLAN interfaces (SVIs).
    Real H3C syntax: 'interface Vlan-interfaceX' (no space).
    Supports: static IP, DHCP server apply, DHCP relay, DHCP client.
    """
    out = []
    for s in svis:
        if not s.get("vlan"): continue
        out.append(f"interface Vlan-interface{s['vlan']}")
        if s.get("description"):
            out.append(f" description {s['description']}")

        dhcp_mode = s.get("dhcp_mode", "none")

        # IP Address handling
        if dhcp_mode == "client":
            # Client mode: get IP from upstream DHCP
            out.append(f" ip address dhcp-alloc")
        elif s.get("ip"):
            try:
                ip_addr, cidr = s["ip"].split("/")
                mask = cidr_to_mask(cidr)
                out.append(f" ip address {ip_addr} {mask}")
            except Exception:
                pass

        # DHCP mode handling
        if dhcp_mode == "server" and s.get("dhcp_apply_pool"):
            out.append(f" dhcp server apply ip-pool {s['dhcp_apply_pool']}")
        elif dhcp_mode == "relay" and s.get("dhcp_relay"):
            out.append(f" dhcp select relay")
            out.append(f" dhcp relay server-address {s['dhcp_relay']}")

        if s.get("shutdown"):
            out.append(" shutdown")
        out.append("#")
    return out

def gen_interface_block(interfaces):
    """
    Physical interface config.
    FIXED: Added 'undo port trunk permit vlan 1' on trunks (security best practice).
    """
    out = []
    for i in interfaces:
        if not i.get("interface"): continue
        out.append(f"interface {i['interface']}")
        if i.get("description"):
            out.append(f" description {i['description']}")
        mode = i.get("mode", "access")
        if mode == "access":
            out.append(" port link-type access")
            if i.get("vlan"):
                out.append(f" port access vlan {i['vlan']}")
        elif mode == "trunk":
            out.append(" port link-type trunk")
            # Security best practice — remove default vlan 1
            out.append(" undo port trunk permit vlan 1")
            if i.get("allowed"):
                out.append(f" port trunk permit vlan {i['allowed']}")
            if i.get("pvid"):
                out.append(f" port trunk pvid vlan {i['pvid']}")
        elif mode == "hybrid":
            out.append(" port link-type hybrid")
            out.append(" undo port hybrid vlan 1")
            if i.get("untagged"):
                out.append(f" port hybrid vlan {i['untagged']} untagged")
            if i.get("tagged"):
                out.append(f" port hybrid vlan {i['tagged']} tagged")
        if i.get("stp_edge"):
            out.append(" stp edged-port")
        if i.get("poe"):
            out.append(" poe enable")
        if i.get("shutdown"):
            out.append(" shutdown")
        out.append("#")
    return out

def gen_dhcp_pool_block(pools):
    """
    DHCP pools.
    FIXED: gateway-list before network (real H3C order).
    FIXED: Multiple forbidden-ip entries supported.
    """
    out = []
    if not pools: return out
    out.append(" dhcp enable")
    out.append("#")
    for p in pools:
        if not p.get("pool_name"): continue
        out.append(f"dhcp server ip-pool {p['pool_name']}")
        if p.get("gateway"):
            out.append(f" gateway-list {p['gateway']}")
        if p.get("network") and p.get("cidr"):
            mask = cidr_to_mask(p["cidr"])
            out.append(f" network {p['network']} mask {mask}")
        if p.get("dns"):
            out.append(f" dns-list {p['dns']}")
        if p.get("lease_days"):
            out.append(f" expired day {p['lease_days']}")
        if p.get("domain"):
            out.append(f" domain-name {p['domain']}")
        # Multi-IP forbidden support (common real pattern)
        forbidden = p.get("forbidden_ips")
        if forbidden:
            if isinstance(forbidden, str):
                for ip in forbidden.replace(",", " ").split():
                    if ip.strip():
                        out.append(f" forbidden-ip {ip.strip()}")
            elif isinstance(forbidden, list):
                for ip in forbidden:
                    if ip and ip.strip():
                        out.append(f" forbidden-ip {ip.strip()}")
        # Legacy range
        if p.get("exclude_start") and p.get("exclude_end"):
            out.append(f" forbidden-ip {p['exclude_start']} {p['exclude_end']}")
        out.append("#")
    return out

def gen_static_route_block(routes):
    out = []
    for r in routes:
        if not (r.get("network") and r.get("cidr") and r.get("next_hop")): continue
        mask = cidr_to_mask(r["cidr"])
        line = f" ip route-static {r['network']} {mask} {r['next_hop']}"
        if r.get("preference"):
            line += f" preference {r['preference']}"
        if r.get("description"):
            line += f" description {r['description']}"
        out.append(line)
    if out:
        out.append("#")
    return out

def gen_ospf_block(ospf):
    """
    FIXED: router-id on same line as 'ospf X'.
    FIXED: area in 0.0.0.0 format.
    """
    out = []
    if not ospf or not ospf.get("process_id"): return out
    if ospf.get("router_id"):
        out.append(f"ospf {ospf['process_id']} router-id {ospf['router_id']}")
    else:
        out.append(f"ospf {ospf['process_id']}")
    if ospf.get("area") is not None and ospf.get("area") != "":
        area_fmt = format_area(ospf['area'])
        out.append(f" area {area_fmt}")
        for net in ospf.get("networks", []):
            if net.get("network") and net.get("cidr"):
                wildcard = cidr_to_wildcard(net["cidr"])
                out.append(f"  network {net['network']} {wildcard}")
    out.append("#")
    return out

def gen_acl_block(acls):
    """
    FIXED: Uses 'acl advanced N' for 3000-3999, 'acl basic N' for 2000-2999.
    FIXED: Includes 'ip' protocol keyword and wildcard mask.
    """
    out = []
    for a in acls:
        num = a.get("acl_number")
        if not num: continue
        try:
            n = int(num)
        except:
            continue
        if 2000 <= n <= 2999:
            acl_type = "basic"
        elif 3000 <= n <= 3999:
            acl_type = "advanced"
        else:
            acl_type = "advanced"
        out.append(f"acl {acl_type} {n}")
        if a.get("description"):
            out.append(f" description {a['description']}")
        for rule in a.get("rules", []):
            if rule.get("action") and rule.get("source"):
                rid = rule.get('rule_id', '').strip()
                action = rule['action']
                protocol = rule.get("protocol", "ip")
                source = rule['source']

                if source.lower() == "any":
                    line = f" rule {rid} {action} {protocol} source any"
                else:
                    wildcard = rule.get("wildcard")
                    if not wildcard and "/" in source:
                        addr, cidr = source.split("/")
                        wildcard = cidr_to_wildcard(cidr)
                        source = addr
                    if wildcard:
                        line = f" rule {rid} {action} {protocol} source {source} {wildcard}"
                    else:
                        line = f" rule {rid} {action} {protocol} source {source} 0"

                line = " " + " ".join(line.split())

                if rule.get("destination"):
                    dest = rule["destination"]
                    dest_wc = rule.get("dest_wildcard", "0")
                    if dest.lower() == "any":
                        line += f" destination any"
                    else:
                        line += f" destination {dest} {dest_wc}"

                out.append(line)
        out.append("#")
    return out

# ==========================================================
# MASTER GENERATOR
# ==========================================================
def generate_config(data):
    """
    Build the full H3C Comware v7 config.
    Real config format with '#' as block separator.
    """
    config = [
        "#",
        f"# Generated by {APP_NAME} v{APP_VERSION}",
        "# Vendor: H3C · OS: Comware v7",
        "# https://configlabs.online",
        "#",
    ]

    # System block
    system_out = gen_system_block(data.get("system"))
    if system_out:
        config.extend(system_out)

    # VLANs (L2)
    vlans = data.get("vlans", [])
    if vlans:
        config.extend(gen_vlan_block(vlans))

    # DHCP Pools — before SVI so "dhcp server apply" references valid pools
    dhcp_out = gen_dhcp_pool_block(data.get("dhcp_pools", []))
    if dhcp_out:
        config.extend(dhcp_out)

    # VLAN Interfaces (SVIs - L3)
    svis = data.get("svis", [])
    if svis:
        config.extend(gen_svi_block(svis))

    # Physical interfaces
    interfaces = data.get("interfaces", [])
    if interfaces:
        config.extend(gen_interface_block(interfaces))

    # Static routes
    routes_out = gen_static_route_block(data.get("static_routes", []))
    if routes_out:
        config.extend(routes_out)

    # OSPF
    ospf_out = gen_ospf_block(data.get("ospf"))
    if ospf_out:
        config.extend(ospf_out)

    # ACLs
    acls_out = gen_acl_block(data.get("acls", []))
    if acls_out:
        config.extend(acls_out)

    # Footer
    config.append("return")
    return "\n".join(config)

# ==========================================================
# TEMPLATES
# ==========================================================
TEMPLATES = {
    "access_switch": {
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
    "core_switch": {
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
    "trunk_uplink": {
        "name": "🔗 Trunk Uplink",
        "description": "Simple trunk link between switches",
        "data": {
            "interfaces": [
                {"interface": "GigabitEthernet1/0/24", "mode": "trunk", "allowed": "10 20 30 99", "description": "Trunk to SW-CORE"}
            ]
        }
    },
    "dhcp_server_vlan": {
        "name": "📡 DHCP Server on VLAN",
        "description": "VLAN + SVI + DHCP pool — full L3 server setup (real-world pattern!)",
        "data": {
            "vlans": [
                {"vlan": "10", "name": "USERS", "description": "Office users"}
            ],
            "dhcp_pools": [{
                "pool_name": "USERS_POOL",
                "network": "10.10.10.0", "cidr": "24",
                "gateway": "10.10.10.1",
                "dns": "8.8.8.8 1.1.1.1",
                "lease_days": "7",
                "forbidden_ips": "10.10.10.1 10.10.10.2 10.10.10.3"
            }],
            "svis": [{
                "vlan": "10", "description": "Users gateway",
                "ip": "10.10.10.1/24",
                "dhcp_mode": "server", "dhcp_apply_pool": "USERS_POOL"
            }]
        }
    },
    "guest_wifi_vlan": {
        "name": "📶 Guest WiFi VLAN",
        "description": "Isolated guest VLAN with DHCP server + ACL",
        "data": {
            "vlans": [
                {"vlan": "200", "name": "GUEST_WIFI", "description": "Guest WiFi isolation"}
            ],
            "dhcp_pools": [{
                "pool_name": "GUEST_POOL",
                "network": "192.168.200.0", "cidr": "24",
                "gateway": "192.168.200.1",
                "dns": "8.8.8.8",
                "lease_days": "1",
                "forbidden_ips": "192.168.200.1"
            }],
            "svis": [{
                "vlan": "200", "description": "Guest WiFi",
                "ip": "192.168.200.1/24",
                "dhcp_mode": "server", "dhcp_apply_pool": "GUEST_POOL"
            }],
            "acls": [{
                "acl_number": "3000",
                "description": "Guest-Isolation",
                "rules": [
                    {"rule_id": "5", "action": "deny", "protocol": "ip", "source": "192.168.200.0", "wildcard": "0.0.0.255"},
                    {"rule_id": "10", "action": "permit", "protocol": "ip", "source": "any"}
                ]
            }]
        }
    },
    "ospf_router": {
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
    "dhcp_relay_vlan": {
        "name": "↗️ DHCP Relay",
        "description": "VLAN with DHCP Relay to central server",
        "data": {
            "vlans": [
                {"vlan": "50", "name": "BRANCH_USERS", "description": "Branch office users"}
            ],
            "svis": [{
                "vlan": "50", "description": "Branch gateway",
                "ip": "172.16.50.1/24",
                "dhcp_mode": "relay", "dhcp_relay": "10.10.100.10"
            }]
        }
    }
}

# ==========================================================
# ROUTES
# ==========================================================
@app.route("/")
def root():
    return jsonify({
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "vendor": CURRENT_VENDOR,
        "docs": "https://configlabs.online"
    })

@app.route("/vendors", methods=["GET"])
def vendors():
    return jsonify(SUPPORTED_VENDORS)

@app.route("/generate", methods=["POST"])
def generate():
    try:
        data = request.json or {}
        result = generate_config(data)
        lines = len(result.split("\n"))
        return jsonify({"config": result, "lines": lines, "success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 400

@app.route("/templates", methods=["GET"])
def templates():
    return jsonify(TEMPLATES)

@app.route("/feedback", methods=["POST"])
def feedback():
    """Simple feedback endpoint — logs to console"""
    try:
        data = request.json or {}
        msg = data.get("message", "")
        email = data.get("email", "anonymous")
        print(f"[FEEDBACK v{APP_VERSION}] from={email} msg={msg[:300]}")
        return jsonify({"success": True, "message": "Thanks for your feedback!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

# ==========================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
