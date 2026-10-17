/* Sample diagram used by the Topology pages */
const TG_TYPES_OK = 1;
function exampleDoc() {
  const D = (id, t, x, y, label, o) => Object.assign({ id, k: 'dev', t, x, y, label, vendor: '', model: '', ip: '', note: '', s: 1, c: '' }, o || {});
  const L = (a, b, type, la, lb, label) => ({ id: 'l_' + a + b, a, b, type, route: 'orth', la: la || '', lb: lb || '', label: label || '', c: '', wd: 0 });
  return { name: 'Campus example', items: [
    { id: 'z1', k: 'box', x: 60, y: 520, w: 380, h: 300, label: 'Floor 1 · VLAN 10 Office', c: '#7cf4c7' }, { id: 'z2', k: 'box', x: 480, y: 520, w: 380, h: 300, label: 'Floor 2 · VLAN 20 Staff', c: '#a8b5ff' }, { id: 'z3', k: 'box', x: 900, y: 520, w: 260, h: 300, label: 'Server room · VLAN 99', c: '#ffb86b' },
    D('isp', 'cloud', 580, 60, 'Internet'), D('fw', 'fw', 580, 190, 'FW-01', { vendor: 'H3C', model: 'F1000' }), D('core', 'l3sw', 580, 340, 'CORE-01', { vendor: 'H3C', model: 'S6520X', ip: '10.0.0.1/24' }),
    D('a1', 'l2sw', 250, 600, 'SW-F1', { vendor: 'H3C', model: 'S5130S-28S' }), D('a2', 'l2sw', 670, 600, 'SW-F2', { vendor: 'H3C', model: 'S5130S-28S' }), D('srv', 'server', 1030, 600, 'SRV-01'),
    D('ap1', 'ap', 130, 750, 'AP-01', { s: .85 }), D('ap2', 'ap', 250, 750, 'AP-02', { s: .85 }), D('pc1', 'pc', 370, 750, 'PC-01', { s: .85 }),
    D('ap3', 'ap', 550, 750, 'AP-03', { s: .85 }), D('ap4', 'ap', 670, 750, 'AP-04', { s: .85 }), D('prn', 'printer', 790, 750, 'PRN-01', { s: .85 }), D('nas', 'nas', 1030, 750, 'NAS-01', { s: .85 })
  ], links: [L('isp', 'fw', 'wan', 'Handoff', 'GE0/0', '1G'), L('fw', 'core', 'fiber', 'XGE0/1', 'XGE1/0/1', '10G'), L('core', 'a1', 'trunk', 'XGE1/0/2', 'XGE1/0/25', '10G · VLAN 10'), L('core', 'a2', 'trunk', 'XGE1/0/3', 'XGE1/0/25', '10G · VLAN 20'), L('core', 'srv', 'fiber', 'XGE1/0/4', 'eth0', '10G'),
    L('a1', 'ap1', 'copper', 'GE1/0/1'), L('a1', 'ap2', 'copper', 'GE1/0/2'), L('a1', 'pc1', 'copper', 'GE1/0/3'), L('a2', 'ap3', 'copper', 'GE1/0/1'), L('a2', 'ap4', 'copper', 'GE1/0/2'), L('a2', 'prn', 'copper', 'GE1/0/3'), L('srv', 'nas', 'copper', 'eth1', 'eth0')] };
}

