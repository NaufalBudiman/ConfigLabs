"""
ConfigLabs — Multi-vendor Network Config Generator
Version 1.1.0 — Week 1 Fixes (Real H3C Syntax Compliance)

What's new in v1.1:
-------------------
[FIX] DHCP server apply on VLAN interfaces (links pool to VLAN)
[FIX] Replaced 'quit' with '#' as block separator (real H3C format)
[FIX] Fixed 'Vlan-interface X' → 'Vlan-interfaceX' (no space)
[FIX] Added 'undo port trunk permit vlan 1' on all trunks (security)
[FIX] ACL: 'acl advanced N' + 'permit ip' + wildcard mask
[FIX] OSPF router-id on same line, area 0.0.0.0 format
[FIX] DHCP multiple forbidden-ip entries supported
[NEW] VLAN range support (10 to 20)
[NEW] Feedback endpoint
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
    """Format OSPF area as 0.0.0.0 or a.b.c.d"""
    area = str(area).strip()
    if not area:
        return "0.0.0.0"
    if "." in area:
        return area
    # Convert plain number to dotted format
    try:
        n = int(area)
        return f"{(n >> 24) & 0xff}.{(n >> 16) & 0xff}.{(n >> 8) & 0xff}.{n & 0xff}"
    except:
        return area

# ==========================================================
# GENERATORS (H3C Comware v7 — verified syntax)
# ==========================================================
def gen_system_block(system):
    """System-level global settings"""
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
    """VLAN creation (L2 only, no IP)"""
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

def gen_svi_block(vlans):
    """
    Layer 3 SVI (Vlan-interface) with IP and DHCP options.
    FIXED: No space between 'Vlan-interface' and number.
    NEW: Supports dhcp_mode = server/relay/client + apply_pool.
    """
    out = []
    for v in vlans:
        if not (v.get("vlan") and v.get("ip")): continue
        try:
            ip_addr, cidr = v["ip"].split("/")
            mask = cidr_to_mask(cidr)
        except Exception:
            continue
        # No space here! Real H3C syntax.
        out.append(f"interface Vlan-interface{v['vlan']}")
        if v.get("description"):
            out.append(f" description {v['description']}")
        out.append(f" ip address {ip_addr} {mask}")

        # DHCP mode on VLAN interface
        dhcp_mode = v.get("dhcp_mode", "none")
        if dhcp_mode == "server" and v.get("dhcp_apply_pool"):
            # Most common pattern in real configs
            out.append(f" dhcp server apply ip-pool {v['dhcp_apply_pool']}")
        elif dhcp_mode == "relay" and v.get("dhcp_relay"):
            out.append(f" dhcp select relay")
            out.append(f" dhcp relay server-address {v['dhcp_relay']}")
        elif dhcp_mode == "client":
            # Override the static IP with dhcp-alloc if client mode is selected
            # Remove the "ip address" line we added above
            out.pop()  # pops the ip address line
            out.append(f" ip address dhcp-alloc")

        # Legacy fallback: if dhcp_relay is set but no mode specified
        if dhcp_mode == "none" and v.get("dhcp_relay"):
            out.append(f" dhcp select relay")
            out.append(f" dhcp relay server-address {v['dhcp_relay']}")

        if v.get("shutdown"):
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
    DHCP server pools.
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
        # Real H3C config order: gateway first, then network
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
        # Multiple forbidden IPs (common real-world pattern)
        # Accepts: single string "10.10.10.1" or list ["10.10.10.1", "10.10.10.2"]
        forbidden = p.get("forbidden_ips")
        if forbidden:
            if isinstance(forbidden, str):
                # split space or newline separated
                for ip in forbidden.replace(",", " ").split():
                    if ip.strip():
                        out.append(f" forbidden-ip {ip.strip()}")
            elif isinstance(forbidden, list):
                for ip in forbidden:
                    if ip.strip():
                        out.append(f" forbidden-ip {ip.strip()}")
        # Legacy range-based exclusion (still supported)
        if p.get("exclude_start") and p.get("exclude_end"):
            out.append(f" forbidden-ip {p['exclude_start']} {p['exclude_end']}")
        out.append("#")
    return out

def gen_static_route_block(routes):
    """Static routes — unchanged but cleaner"""
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
    OSPF routing.
    FIXED: router-id on same line as 'ospf X' (real H3C style).
    FIXED: area formatted as 0.0.0.0.
    """
    out = []
    if not ospf or not ospf.get("process_id"): return out
    # Router-id on same line
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
    ACL generation.
    FIXED: uses 'acl advanced N' for 3000-3999 and 'acl basic N' for 2000-2999.
    FIXED: includes 'ip' protocol keyword and wildcard mask.
    """
    out = []
    for a in acls:
        num = a.get("acl_number")
        if not num: continue
        try:
            n = int(num)
        except:
            continue
        # Determine keyword based on ACL number range
        if 2000 <= n <= 2999:
            acl_type = "basic"
        elif 3000 <= n <= 3999:
            acl_type = "advanced"
        else:
            acl_type = "advanced"  # default fallback
        out.append(f"acl {acl_type} {n}")
        if a.get("description"):
            out.append(f" description {a['description']}")
        for rule in a.get("rules", []):
            if rule.get("action") and rule.get("source"):
                rid = rule.get('rule_id', '').strip()
                action = rule['action']
                protocol = rule.get("protocol", "ip")  # default to 'ip'
                source = rule['source']

                # Build rule line
                if source.lower() == "any":
                    line = f" rule {rid} {action} {protocol} source any".strip()
                    line = " ".join(line.split())  # normalize spaces
                else:
                    # Use wildcard if provided, else derive from CIDR if given
                    wildcard = rule.get("wildcard")
                    if not wildcard and "/" in source:
                        addr, cidr = source.split("/")
                        wildcard = cidr_to_wildcard(cidr)
                        source = addr
                    if wildcard:
                        line = f" rule {rid} {action} {protocol} source {source} {wildcard}"
                    else:
                        line = f" rule {rid} {action} {protocol} source {source} 0"
                    # Clean up extra spaces
                    line = " ".join(line.split())
                    line = " " + line.lstrip()

                # Optional destination
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
    Uses '#' as block separator (real config file format).
    """
    config = [
        "#",
        f"# Generated by {APP_NAME} v{APP_VERSION}",
        "# Vendor: H3C · OS: Comware v7",
        "# https://configlabs.online",
        "#",
    ]

    # System block (global settings)
    system_out = gen_system_block(data.get("system"))
    if system_out:
        config.extend(system_out)

    # VLANs (L2)
    vlans = data.get("vlans", [])
    if vlans:
        config.extend(gen_vlan_block(vlans))

    # DHCP Pools (must exist before VLAN interfaces reference them)
    dhcp_out = gen_dhcp_pool_block(data.get("dhcp_pools", []))
    if dhcp_out:
        config.extend(dhcp_out)

    # Layer 3 VLAN interfaces (SVIs) with DHCP apply
    svi_out = gen_svi_block(vlans)
    if svi_out:
        config.extend(svi_out)

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
# TEMPLATES — updated to use new dhcp_mode and dhcp_apply_pool
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
                {"vlan": "10", "name": "USERS", "ip": "10.10.10.1/24"},
                {"vlan": "20", "name": "SERVERS", "ip": "10.10.20.1/24"},
                {"vlan": "99", "name": "MGMT", "ip": "10.10.99.1/24"}
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
    "dhcp_server_with_vlan": {
        "name": "📡 DHCP on VLAN (L3 + Pool)",
        "description": "VLAN interface with DHCP server apply — real-world setup",
        "data": {
            "vlans": [{
                "vlan": "10", "name": "USERS", "description": "Office users",
                "ip": "10.10.10.1/24",
                "dhcp_mode": "server", "dhcp_apply_pool": "USERS_POOL"
            }],
            "dhcp_pools": [{
                "pool_name": "USERS_POOL",
                "network": "10.10.10.0", "cidr": "24",
                "gateway": "10.10.10.1",
                "dns": "8.8.8.8 1.1.1.1",
                "lease_days": "7",
                "forbidden_ips": "10.10.10.1 10.10.10.2 10.10.10.3"
            }]
        }
    },
    "guest_wifi_vlan": {
        "name": "📶 Guest WiFi VLAN",
        "description": "Isolated guest VLAN with DHCP and ACL",
        "data": {
            "vlans": [{
                "vlan": "200", "name": "GUEST_WIFI",
                "ip": "192.168.200.1/24",
                "dhcp_mode": "server", "dhcp_apply_pool": "GUEST_POOL"
            }],
            "dhcp_pools": [{
                "pool_name": "GUEST_POOL",
                "network": "192.168.200.0", "cidr": "24",
                "gateway": "192.168.200.1",
                "dns": "8.8.8.8",
                "lease_days": "1",
                "forbidden_ips": "192.168.200.1"
            }],
            "acls": [{
                "acl_number": "3000",
                "description": "Guest-WiFi-Isolation",
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
        "name": "↗️ DHCP Relay VLAN",
        "description": "VLAN with DHCP Relay to central server",
        "data": {
            "vlans": [{
                "vlan": "50", "name": "BRANCH_USERS",
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
    """Simple feedback endpoint — logs to console for now"""
    try:
        data = request.json or {}
        msg = data.get("message", "")
        email = data.get("email", "anonymous")
        print(f"[FEEDBACK] from={email} msg={msg[:200]}")
        return jsonify({"success": True, "message": "Thanks for your feedback!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

# ==========================================================
if __name__ == "__main__":
    # Port 5002 for test bench (production uses Railway's PORT env var)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)