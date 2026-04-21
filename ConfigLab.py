"""
ConfigLab — Multi-vendor Network Config Generator
H3C Comware v7 (more vendors coming soon)
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)

APP_NAME = "ConfigLab"
APP_VERSION = "1.0.0"
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

# ==========================================================
# GENERATORS (H3C Comware)
# ==========================================================
def gen_vlan_block(vlans):
    out = []
    for v in vlans:
        if not v.get("vlan"): continue
        out.append(f"vlan {v['vlan']}")
        if v.get("name"): out.append(f" name {v['name']}")
        if v.get("description"): out.append(f" description {v['description']}")
        out.append("quit")
    return out

def gen_svi_block(vlans):
    out = []
    for v in vlans:
        if not (v.get("vlan") and v.get("ip")): continue
        try:
            ip_addr, cidr = v["ip"].split("/")
            mask = cidr_to_mask(cidr)
        except Exception: continue
        out.append(f"interface Vlan-interface {v['vlan']}")
        if v.get("description"): out.append(f" description {v['description']}")
        out.append(f" ip address {ip_addr} {mask}")
        if v.get("dhcp_relay"):
            out.append(f" dhcp select relay")
            out.append(f" dhcp relay server-address {v['dhcp_relay']}")
        out.append("quit")
    return out

def gen_interface_block(interfaces):
    out = []
    for i in interfaces:
        if not i.get("interface"): continue
        out.append(f"interface {i['interface']}")
        if i.get("description"): out.append(f" description {i['description']}")
        mode = i.get("mode", "access")
        if mode == "access":
            out.append(" port link-type access")
            if i.get("vlan"): out.append(f" port access vlan {i['vlan']}")
        elif mode == "trunk":
            out.append(" port link-type trunk")
            if i.get("allowed"): out.append(f" port trunk permit vlan {i['allowed']}")
            if i.get("pvid"): out.append(f" port trunk pvid vlan {i['pvid']}")
        elif mode == "hybrid":
            out.append(" port link-type hybrid")
            if i.get("untagged"): out.append(f" port hybrid vlan {i['untagged']} untagged")
            if i.get("tagged"): out.append(f" port hybrid vlan {i['tagged']} tagged")
        if i.get("stp_edge"): out.append(" stp edged-port")
        if i.get("poe"): out.append(" poe enable")
        if i.get("shutdown"): out.append(" shutdown")
        else: out.append(" undo shutdown")
        out.append("quit")
    return out

def gen_dhcp_pool_block(pools):
    out = []
    if not pools: return out
    out.append("dhcp enable")
    for p in pools:
        if not p.get("pool_name"): continue
        out.append(f"dhcp server ip-pool {p['pool_name']}")
        if p.get("network") and p.get("cidr"):
            mask = cidr_to_mask(p["cidr"])
            out.append(f" network {p['network']} mask {mask}")
        if p.get("gateway"): out.append(f" gateway-list {p['gateway']}")
        if p.get("dns"): out.append(f" dns-list {p['dns']}")
        if p.get("lease_days"): out.append(f" expired day {p['lease_days']}")
        if p.get("domain"): out.append(f" domain-name {p['domain']}")
        out.append("quit")
        if p.get("exclude_start") and p.get("exclude_end"):
            out.append(f"dhcp server forbidden-ip {p['exclude_start']} {p['exclude_end']}")
    return out

def gen_static_route_block(routes):
    out = []
    for r in routes:
        if not (r.get("network") and r.get("cidr") and r.get("next_hop")): continue
        mask = cidr_to_mask(r["cidr"])
        line = f"ip route-static {r['network']} {mask} {r['next_hop']}"
        if r.get("preference"): line += f" preference {r['preference']}"
        if r.get("description"): line += f" description {r['description']}"
        out.append(line)
    return out

def gen_ospf_block(ospf):
    out = []
    if not ospf or not ospf.get("process_id"): return out
    out.append(f"ospf {ospf['process_id']}")
    if ospf.get("router_id"): out.append(f" router-id {ospf['router_id']}")
    if ospf.get("area") is not None:
        out.append(f" area {ospf['area']}")
        for net in ospf.get("networks", []):
            if net.get("network") and net.get("cidr"):
                wildcard = cidr_to_wildcard(net["cidr"])
                out.append(f"  network {net['network']} {wildcard}")
        out.append(" quit")
    out.append("quit")
    return out

def gen_acl_block(acls):
    out = []
    for a in acls:
        if not a.get("acl_number"): continue
        out.append(f"acl number {a['acl_number']}")
        for rule in a.get("rules", []):
            if rule.get("action") and rule.get("source"):
                line = f" rule {rule.get('rule_id', '')} {rule['action']} source {rule['source']}".strip()
                if rule.get("wildcard"): line += f" {rule['wildcard']}"
                out.append(line)
        out.append("quit")
    return out

def gen_system_block(system):
    out = []
    if not system: return out
    if system.get("hostname"): out.append(f"sysname {system['hostname']}")
    if system.get("banner"): out.append(f"header shell {system['banner']}")
    if system.get("ntp"): out.append(f"ntp-service unicast-server {system['ntp']}")
    if system.get("timezone"): out.append(f"clock timezone {system['timezone']}")
    return out

# ==========================================================
# MASTER GENERATOR
# ==========================================================
def generate_config(data):
    config = [
        "#",
        f"# Generated by {APP_NAME} v{APP_VERSION}",
        "# Vendor: H3C · OS: Comware v7",
        "#",
        "system-view"
    ]
    system_out = gen_system_block(data.get("system"))
    if system_out:
        config.extend(["#", "# System Configuration"])
        config.extend(system_out)
    vlans = data.get("vlans", [])
    if vlans:
        config.extend(["#", "# VLAN Configuration"])
        config.extend(gen_vlan_block(vlans))
    svi_out = gen_svi_block(vlans)
    if svi_out:
        config.extend(["#", "# Layer 3 VLAN Interfaces"])
        config.extend(svi_out)
    interfaces = data.get("interfaces", [])
    if interfaces:
        config.extend(["#", "# Interface Configuration"])
        config.extend(gen_interface_block(interfaces))
    dhcp_out = gen_dhcp_pool_block(data.get("dhcp_pools", []))
    if dhcp_out:
        config.extend(["#", "# DHCP Server Configuration"])
        config.extend(dhcp_out)
    routes_out = gen_static_route_block(data.get("static_routes", []))
    if routes_out:
        config.extend(["#", "# Static Routing"])
        config.extend(routes_out)
    ospf_out = gen_ospf_block(data.get("ospf"))
    if ospf_out:
        config.extend(["#", "# OSPF Configuration"])
        config.extend(ospf_out)
    acls_out = gen_acl_block(data.get("acls", []))
    if acls_out:
        config.extend(["#", "# Access Control Lists"])
        config.extend(acls_out)
    config.extend(["#", "save force", "quit"])
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
    "dhcp_server": {
        "name": "📡 DHCP Server",
        "description": "DHCP server with pool, gateway and DNS",
        "data": {
            "dhcp_pools": [
                {"pool_name": "USERS_POOL", "network": "10.10.10.0", "cidr": "24",
                 "gateway": "10.10.10.1", "dns": "8.8.8.8 1.1.1.1",
                 "lease_days": "7", "domain": "company.local",
                 "exclude_start": "10.10.10.1", "exclude_end": "10.10.10.20"}
            ]
        }
    },
    "guest_wifi_vlan": {
        "name": "📶 Guest WiFi VLAN",
        "description": "Isolated guest VLAN with DHCP and ACL",
        "data": {
            "vlans": [{"vlan": "200", "name": "GUEST_WIFI", "ip": "192.168.200.1/24"}],
            "dhcp_pools": [
                {"pool_name": "GUEST_POOL", "network": "192.168.200.0", "cidr": "24",
                 "gateway": "192.168.200.1", "dns": "8.8.8.8", "lease_days": "1"}
            ],
            "acls": [
                {"acl_number": "3000", "rules": [
                    {"rule_id": "5", "action": "deny", "source": "192.168.200.0"},
                    {"rule_id": "10", "action": "permit", "source": "any"}
                ]}
            ]
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
        "vendor": CURRENT_VENDOR
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

# ==========================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
