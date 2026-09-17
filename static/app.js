async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || '操作失敗');
  return data;
}
function toast(message) { const el = document.getElementById('toast'); el.textContent = message; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 2600); }
function byId(id) { return document.getElementById(id); }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character])); }
function riskClass(risk) { return risk === '中高風險' ? 'danger' : risk === '注意' ? 'warning' : 'ok'; }
function deviceStatusClass(status) { return status === '連線中' ? 'online' : status === '離線' ? 'offline' : 'waiting'; }

async function loadSummary() { try { const s = await api('/api/summary'); byId('totalPeople').textContent=s.people; byId('ppeAlerts').textContent=s.ppe_alerts; byId('riskCount').textContent=s.risks; byId('peopleText').textContent=s.people; } catch(e) {} }

let monitoringDevicesCache = [];
async function loadMonitoringDevices() {
  monitoringDevicesCache = await api('/api/monitoring-devices');
  const rows = byId('monitoringDeviceRows');
  if (!monitoringDevicesCache.length) {
    rows.innerHTML = '<tr><td class="empty-table-cell" colspan="6">目前尚無監控設備</td></tr>';
    return;
  }
  rows.innerHTML = monitoringDevicesCache.map(device => `
    <tr>
      <td><b>${escapeHtml(device.id)}</b></td>
      <td>${escapeHtml(device.location)}</td>
      <td><span class="monitor-status ${device.status === '正常' ? 'online' : device.status === '離線' ? 'offline' : 'waiting'}"><i></i>${escapeHtml(device.status)}</span></td>
      <td>${escapeHtml(device.last_seen || '尚未收到資料')}</td>
      <td class="stream-url-cell">${device.stream_url ? `<a href="${escapeHtml(device.stream_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(device.stream_url)}">${escapeHtml(device.stream_url)}</a>` : '<span class="muted">尚未設定</span>'}</td>
      <td>
        <button class="text-button" onclick="openMonitoringDeviceForm('${device.id}')">編輯</button>
        <button class="text-button delete-text" onclick="removeMonitoringDevice('${device.id}')">刪除</button>
      </td>
    </tr>
  `).join('');
}
function openMonitoringDeviceForm(deviceId='') {
  byId('monitoringDeviceForm').reset();
  byId('editMonitoringDeviceId').value = deviceId;
  const device = monitoringDevicesCache.find(item => item.id === deviceId);
  byId('monitoringDeviceDialogTitle').textContent = device ? '編輯監控設備' : '新增監控設備';
  byId('saveMonitoringDeviceButton').textContent = device ? '儲存變更' : '新增設備';
  byId('monitoringDeviceId').readOnly = !!device;
  if (device) {
    byId('monitoringDeviceId').value = device.id;
    byId('monitoringDeviceLocation').value = device.location;
    byId('monitoringDeviceStreamUrl').value = device.stream_url || '';
  }
  byId('monitoringDeviceDialog').showModal();
}
async function saveMonitoringDevice(event) {
  event.preventDefault();
  const currentId = byId('editMonitoringDeviceId').value;
  const body = {
    id: byId('monitoringDeviceId').value,
    location: byId('monitoringDeviceLocation').value,
    stream_url: byId('monitoringDeviceStreamUrl').value
  };
  try {
    await api(currentId ? '/api/monitoring-devices/' + encodeURIComponent(currentId) : '/api/monitoring-devices', {
      method: currentId ? 'PUT' : 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    byId('monitoringDeviceDialog').close();
    toast(currentId ? '監控設備已更新' : '監控設備已新增');
    loadMonitoringDevices();
  } catch(e) { toast(e.message); }
}
async function removeMonitoringDevice(deviceId) {
  if (!confirm(`確定要刪除監控設備 ${deviceId}？`)) return;
  try {
    await api('/api/monitoring-devices/' + encodeURIComponent(deviceId), {method:'DELETE'});
    toast('監控設備已刪除');
    loadMonitoringDevices();
  } catch(e) { toast(e.message); }
}

let peopleCache = [];
function isWaitingForPersonData(person) {
  return (person.device_status || '等待資料') === '等待資料' || !person.last_seen;
}

async function loadPeople() {
  peopleCache = await api('/api/people');
  const options = byId('deviceNameOptions');
  if (options) {
    options.innerHTML = peopleCache.map(p => `<option value="${p.name || p.id}"></option>`).join('');
  }
  byId('peopleRows').innerHTML = peopleCache.map(p => {
    const waitingForData = isWaitingForPersonData(p);
    const positionCell = waitingForData
      ? '<span class="pending-data">等待資料</span>'
      : `X ${Number(p.x ?? 0).toFixed(1)}／Y ${Number(p.y ?? 0).toFixed(1)}／Z ${Number(p.z ?? 0).toFixed(1)}`;
    const batteryCell = waitingForData
      ? '<span class="pending-data">等待資料</span>'
      : `<span class="battery-display">
          <strong>${Number(p.battery ?? 0)}%</strong>
          <i><b style="width:${Math.max(0,Math.min(100,Number(p.battery ?? 0)))}%"></b></i>
        </span>`;
    const riskCell = waitingForData
      ? '<span class="pending-data">等待資料</span>'
      : `<span class="badge ${riskClass(p.risk)}">${p.risk || '低風險'}</span>`;
    return `
    <tr>
      <td><b>${p.employee_name || '未綁定'}</b></td>
      <td><span>${p.name || p.id}</span></td>
      <td class="${waitingForData ? '' : 'mono'}">${positionCell}</td>
      <td>${batteryCell}</td>
      <td>${riskCell}</td>
      <td>
        <span class="device-state ${deviceStatusClass(p.device_status)}"><i></i>${p.device_status || '等待資料'}</span>
        ${p.last_seen ? `<small class="last-seen">${p.last_seen}</small>` : ''}
      </td>
      <td>
        <button class="text-button" onclick="openDeviceForm('${p.id}')">編輯</button>
        <button class="text-button delete-text" onclick="removeDevice('${p.id}')">移除</button>
      </td>
    </tr>
  `;
  }).join('');
}


let areasCache = [];
async function loadAreas() {
  areasCache = await api('/api/areas');
  const container = byId('areaCards');
  if (!areasCache.length) {
    container.innerHTML = '<section class="area-empty-state">目前尚無區域，請先新增區域。</section>';
    return;
  }
  container.innerHTML = areasCache.map(area => {
    const stationRows = area.stations.length ? area.stations.map(station => `
      <tr>
        <td><b>${escapeHtml(station.name)}</b></td>
        <td class="mono">X: ${Number(station.x).toFixed(1)} / Y: ${Number(station.y).toFixed(1)} / Z: ${Number(station.z).toFixed(1)}</td>
        <td><button class="text-button delete-text" onclick="removeBaseStation('${station.id}')">移除</button></td>
      </tr>
    `).join('') : '<tr><td class="empty-table-cell" colspan="3">目前尚無基站</td></tr>';
    return `
      <section class="area-card">
        <div class="area-card-heading">
          <h2>${escapeHtml(area.name)}</h2>
          <div class="area-card-actions">
            <button class="text-button delete-text" onclick="removeArea(${area.id}, ${area.stations.length})">刪除區域</button>
            <button class="primary" onclick="openBaseStationForm(${area.id})">＋ 新增基站</button>
          </div>
        </div>
        <div class="table-scroll">
          <table>
            <thead><tr><th>裝置名稱</th><th>位子</th><th>操作</th></tr></thead>
            <tbody>${stationRows}</tbody>
          </table>
        </div>
      </section>
    `;
  }).join('');
}

function openAreaForm() {
  byId('areaForm').reset();
  byId('areaDialog').showModal();
}

async function saveArea(event) {
  event.preventDefault();
  try {
    await api('/api/areas', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name: byId('areaName').value})
    });
    byId('areaDialog').close();
    toast('區域已新增');
    loadAreas();
  } catch(e) { toast(e.message); }
}

async function removeArea(id, stationCount) {
  const area = areasCache.find(item => item.id === id);
  const name = area ? area.name : `#${id}`;
  const stationWarning = stationCount
    ? `此區域內有 ${stationCount} 個 UWB 基站，刪除區域時也會一併刪除。`
    : '此操作無法復原。';
  if (!confirm(`確定要刪除區域「${name}」？\n${stationWarning}`)) return;
  try {
    await api('/api/areas/' + encodeURIComponent(id), {method:'DELETE'});
    toast('區域已刪除');
    loadAreas();
  } catch(e) { toast(e.message); }
}

function openBaseStationForm(areaId) {
  const area = areasCache.find(item => item.id === areaId);
  byId('baseStationForm').reset();
  byId('baseStationAreaId').value = areaId;
  byId('baseStationX').value = 0;
  byId('baseStationY').value = 0;
  byId('baseStationZ').value = 0;
  byId('baseStationDialogTitle').textContent = `新增 UWB 基站｜${area ? area.name : ''}`;
  byId('baseStationDialog').showModal();
}

async function saveBaseStation(event) {
  event.preventDefault();
  const body = {
    area_id: byId('baseStationAreaId').value,
    name: byId('baseStationName').value,
    x: byId('baseStationX').value,
    y: byId('baseStationY').value,
    z: byId('baseStationZ').value
  };
  try {
    await api('/api/base-stations', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    byId('baseStationDialog').close();
    toast('UWB 基站已新增');
    loadAreas();
  } catch(e) { toast(e.message); }
}

async function removeBaseStation(id) {
  if (!confirm('確定要移除此 UWB 基站？')) return;
  try {
    await api('/api/base-stations/' + encodeURIComponent(id), {method:'DELETE'});
    toast('UWB 基站已移除');
    loadAreas();
  } catch(e) { toast(e.message); }
}

async function togglePpe(id, key, value) { try { await api('/api/people/'+id, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({[key]:value?0:1})}); toast('PPE 狀態已更新'); loadPeople(); } catch(e) { toast(e.message); } }
async function cycleRisk(id, risk) { const next={'低風險':'注意','注意':'中高風險','中高風險':'低風險'}[risk]; try { await api('/api/people/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({risk:next})}); toast('風險已更新為 '+next); loadPeople(); } catch(e) { toast(e.message); } }
function openDeviceForm(personId='') {
  byId('deviceForm').reset();
  byId('editPersonId').value = personId;
  const person = peopleCache.find(item => item.id === personId);
  byId('deviceDialogTitle').textContent = person ? '編輯人員' : '新增人員';
  byId('saveDeviceButton').textContent = person ? '儲存變更' : '新增人員';
  if (person) {
    byId('employeeName').value = person.employee_name === '未綁定' ? '' : (person.employee_name || '');
    byId('deviceName').value = person.name || '';
  }
  byId('deviceDialog').showModal();
}
async function saveDevice(event) {
  event.preventDefault();
  const id = byId('editPersonId').value;
  const body = {
    employee_name: byId('employeeName').value,
    device_name: byId('deviceName').value,
    name: byId('deviceName').value
  };
  try {
    await api(id ? '/api/people/' + encodeURIComponent(id) : '/api/people', {
      method: id ? 'PUT' : 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    byId('deviceDialog').close();
    toast(id ? '人員資料已更新' : '人員已新增');
    loadPeople();
  } catch(e) { toast(e.message); }
}
async function removeDevice(id) { if(!confirm('確定要移除此人員？')) return; try { await api('/api/people/'+id,{method:'DELETE'}); toast('人員已移除'); loadPeople(); } catch(e) { toast(e.message); } }
async function importPeopleFile() {
  const input = byId('peopleImportFile'); if (!input.files.length) return;
  const form = new FormData(); form.append('file', input.files[0]);
  try { const result=await api('/api/people/import',{method:'POST',body:form}); const skipped=result.skipped.length ? `；略過第 ${result.skipped.join('、')} 行` : ''; toast(`已匯入或更新 ${result.imported} 筆${skipped}`); loadPeople(); } catch(e) { toast(e.message); } finally { input.value=''; }
}

let uwbAreasCache = [];
let uwbAreaFilter = 'all';
let selectedUwbAreaId = null;

function uwbTimeAgo(value) {
  if (!value) return '尚未匯入';
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return value;
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp.getTime()) / 1000));
  if (seconds < 60) return '剛剛';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分鐘前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小時前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function normalizedStationPoints(stations, padding = 8) {
  if (!stations.length) return [];
  const xs = stations.map(station => Number(station.x) || 0);
  const ys = stations.map(station => Number(station.y) || 0);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const points = stations.map(station => ({
    ...station,
    px: padding + ((Number(station.x) - minX) / rangeX) * (100 - padding * 2),
    py: padding + ((Number(station.y) - minY) / rangeY) * (100 - padding * 2)
  }));
  const centerX = points.reduce((sum, point) => sum + point.px, 0) / points.length;
  const centerY = points.reduce((sum, point) => sum + point.py, 0) / points.length;
  return points.sort(
    (a, b) => Math.atan2(a.py - centerY, a.px - centerX) - Math.atan2(b.py - centerY, b.px - centerX)
  );
}

function buildUwbAreaPreview(area) {
  const ready = area.external_station_count === 4 && area.stations.length === 4;
  if (!ready) {
    return `
      <div class="uwb-preview uwb-waiting-preview">
        <span>⇧</span>
        <strong>等待 4 個基站資料</strong>
      </div>
    `;
  }
  const points = normalizedStationPoints(area.stations, 10);
  const polygon = points.map(point => `${point.px},${point.py}`).join(' ');
  const markers = points.map(point => `
    <g>
      <circle cx="${point.px}" cy="${point.py}" r="4.1" class="${point.status === '離線' ? 'offline' : ''}"></circle>
      <text x="${point.px}" y="${point.py - 6}" text-anchor="middle">${escapeHtml(point.id)}</text>
      <text x="${point.px}" y="${point.py + 8}" text-anchor="middle">(${Number(point.x).toFixed(1)}, ${Number(point.y).toFixed(1)})</text>
    </g>
  `).join('');
  return `
    <div class="uwb-preview">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="UWB 基站位置預覽">
        <polygon points="${polygon}"></polygon>
        ${markers}
      </svg>
      <div class="uwb-preview-people">
        <span>${area.people_count || 0}</span>
        <small>區域人員</small>
      </div>
    </div>
  `;
}

async function loadUwbAreas() {
  try {
    uwbAreasCache = await api('/api/areas');
    renderUwbAreas();
  } catch (error) {
    const cards = byId('uwbAreaCards');
    if (cards) cards.innerHTML = `<div class="uwb-empty-state">${escapeHtml(error.message)}</div>`;
  }
}

function setUwbAreaFilter(filter, button) {
  uwbAreaFilter = filter;
  document.querySelectorAll('.uwb-filters button').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  renderUwbAreas();
}

function renderUwbAreas() {
  const cards = byId('uwbAreaCards');
  if (!cards) return;
  const query = (byId('uwbAreaSearch')?.value || '').trim().toLowerCase();
  const areas = uwbAreasCache.filter(area => {
    const ready = area.external_station_count === 4 && area.stations.length === 4;
    const hasAlert = Number(area.alert_count) > 0;
    const filterMatch = uwbAreaFilter === 'all' || (uwbAreaFilter === 'ready' ? ready : hasAlert);
    return filterMatch && (!query || area.name.toLowerCase().includes(query));
  });
  if (!areas.length) {
    cards.innerHTML = '<div class="uwb-empty-state">目前沒有符合條件的監控區域</div>';
    return;
  }
  cards.innerHTML = areas.map(area => {
    const ready = area.external_station_count === 4 && area.stations.length === 4;
    const alertCount = Number(area.alert_count) || 0;
    const offlineCount = area.stations.filter(station => station.status === '離線').length;
    const statusClass = !ready ? 'waiting' : alertCount ? 'alert' : offlineCount ? 'waiting' : 'ready';
    const statusText = !ready
      ? '等待外部資料'
      : alertCount ? `${alertCount} 筆越界警示` : offlineCount ? `${offlineCount} 個基站離線` : '正常監控';
    return `
      <article class="uwb-area-card">
        <div class="uwb-card-heading">
          <h2>${escapeHtml(area.name)}</h2>
          <span>›</span>
        </div>
        <div class="uwb-area-status ${statusClass}"><i></i>${statusText}</div>
        <div class="uwb-sync-row">
          <span>↻　外部 UWB 資料：${ready ? '已同步 4 個基站' : '等待 4 個基站資料'}</span>
          <small>最後匯入：${escapeHtml(uwbTimeAgo(area.last_import))}</small>
        </div>
        <div class="uwb-area-meta">
          <span>⌾ ${ready ? 4 : area.external_station_count || 0} / 4 基站</span>
          <span>♙ ${area.people_count || 0} 位人員</span>
        </div>
        ${buildUwbAreaPreview(area)}
        <button ${ready ? `onclick="enterUwbArea(${area.id})"` : 'disabled'}>
          ${ready ? '進入 UWB 監看' : '等待資料'}
        </button>
      </article>
    `;
  }).join('');
}

async function enterUwbArea(areaId) {
  selectedUwbAreaId = areaId;
  byId('uwbAreaSelection').hidden = true;
  byId('uwbMonitorPanel').hidden = false;
  await refreshSelectedUwbArea();
}

function backToUwbAreas() {
  selectedUwbAreaId = null;
  byId('uwbMonitorPanel').hidden = true;
  byId('uwbAreaSelection').hidden = false;
  loadUwbAreas();
}

async function refreshSelectedUwbArea() {
  if (selectedUwbAreaId === null) return;
  try {
    const [areas, people] = await Promise.all([api('/api/areas'), api('/api/people')]);
    uwbAreasCache = areas;
    const area = areas.find(item => item.id === selectedUwbAreaId);
    if (!area) {
      backToUwbAreas();
      toast('此區域已不存在');
      return;
    }
    renderUwbLiveMap(area, people.filter(person => person.area === area.name));
  } catch (error) {
    toast(error.message);
  }
}

function renderUwbLiveMap(area, people) {
  byId('selectedUwbAreaTitle').textContent = `${area.name}｜UWB 即時定位監看`;
  const map = byId('uwbLiveMap');
  const points = normalizedStationPoints(area.stations, 6);
  const polygon = points.map(point => `${point.px},${point.py}`).join(' ');
  const fence = `
    <svg class="uwb-live-fence" viewBox="0 0 100 100" preserveAspectRatio="none">
      <polygon points="${polygon}"></polygon>
    </svg>
  `;
  const stations = points.map(point => `
    <div class="uwb-live-station ${point.status === '離線' ? 'offline' : ''}" style="left:${point.px}%;top:${point.py}%">
      <b>⌾</b>
      <span>${escapeHtml(point.id)}</span>
      <small>X ${Number(point.x).toFixed(1)}・Y ${Number(point.y).toFixed(1)}・Z ${Number(point.z).toFixed(1)}</small>
    </div>
  `).join('');
  const personMarkers = people.map(person => `
    <div class="uwb-live-person ${riskClass(person.risk)}" style="left:${Math.max(2, Math.min(98, Number(person.x) || 0))}%;top:${Math.max(3, Math.min(97, Number(person.y) || 0))}%">
      ${escapeHtml(person.id)}
      <small>${escapeHtml(person.employee_name || person.name)}</small>
    </div>
  `).join('');
  map.innerHTML = `${fence}${stations}${personMarkers}`;
  const alertCount = people.filter(person => person.risk !== '低風險').length;
  const onlineStations = area.stations.filter(station => station.status !== '離線').length;
  byId('uwbStationSummary').textContent = `${onlineStations} / 4 正常`;
  byId('uwbPeopleSummary').textContent = `${people.length} 人`;
  byId('uwbAlertSummary').textContent = `${alertCount} 筆`;
  byId('uwbLastSyncSummary').textContent = uwbTimeAgo(area.last_import);
  byId('uwbMonitorStatus').textContent = alertCount
    ? `偵測到 ${alertCount} 筆注意或越界事件`
    : '每 5 秒同步一次定位資料';
}

async function loadMap() {
  const people=await api('/api/people'); const map=byId('map'); map.querySelectorAll('.person-marker').forEach(e=>e.remove());
  people.forEach(p=>{ const el=document.createElement('button'); el.className='person-marker '+riskClass(p.risk); el.style.left=p.x+'%'; el.style.top=p.y+'%'; el.innerHTML=`${p.id.replace('W-00','')}<small>${p.name}</small>`; el.title='拖曳更新位置；點擊切換風險'; el.onpointerdown=e=>dragMarker(e,el,p); el.onclick=()=>cycleRisk(p.id,p.risk).then(loadMap); map.appendChild(el); });
}
function dragMarker(event, el, person) {
  event.preventDefault(); event.stopPropagation(); let moved=false; const map=byId('map');
  const move=ev=>{moved=true;const box=map.getBoundingClientRect();person.x=Math.max(2,Math.min(96,(ev.clientX-box.left)/box.width*100));person.y=Math.max(3,Math.min(93,(ev.clientY-box.top)/box.height*100));el.style.left=person.x+'%';el.style.top=person.y+'%';};
  const up=async()=>{window.removeEventListener('pointermove',move);if(moved){el.onclick=null;try{await api('/api/people/'+person.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:person.x,y:person.y})});toast('位置已儲存');}catch(e){toast(e.message);}setTimeout(()=>el.onclick=()=>cycleRisk(person.id,person.risk).then(loadMap),100);}};
  window.addEventListener('pointermove',move); window.addEventListener('pointerup',up,{once:true});
}

async function loadUsers() {
  const users=await api('/api/users?q='+encodeURIComponent(byId('userSearch').value));
  byId('userRows').innerHTML=users.map(u=>`<tr><td><strong>${u.account}</strong></td><td>${u.name}</td><td>${u.phone||'—'}</td><td class="user-email-cell">${u.email||'尚未設定'}</td><td><span class="account-role ${u.role==='管理員'?'admin':''}">${u.role}</span></td><td><span class="account-status ${u.active?'active':''}">${u.active?'啟用':'停用'}</span></td><td>${u.created_at||'—'}</td><td><button class="text-button" onclick='openUserForm(${JSON.stringify(u)})'>編輯</button><button class="text-button" onclick="setUserActive(${u.id},${u.active?0:1})">${u.active?'停用':'啟用'}</button><button class="text-button delete-text" onclick="removeUser(${u.id})">刪除</button></td></tr>`).join('');
}
function openUserForm(user) { byId('userForm').reset(); byId('editUserId').value=user?.id||''; byId('dialogTitle').textContent=user?'編輯帳戶':'新增帳戶'; byId('account').value=user?.account||''; byId('name').value=user?.name||''; byId('phone').value=user?.phone||''; byId('email').value=user?.email||''; byId('role').value=user?.role||'一般使用者'; byId('account').disabled=!!user; byId('password').required=!user; byId('userDialog').showModal(); }
async function saveUser(event) {
  event.preventDefault(); const id=byId('editUserId').value; const body={account:byId('account').value,name:byId('name').value,phone:byId('phone').value,email:byId('email').value,role:byId('role').value,password:byId('password').value};
  try { await api(id?'/api/users/'+id:'/api/users',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});byId('userDialog').close();toast('帳戶資料已儲存');loadUsers();} catch(e) {toast(e.message);}
}
async function setUserActive(id,active){try{await api('/api/users/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({active})});toast('帳號狀態已更新');loadUsers();}catch(e){toast(e.message);}}
async function removeUser(id){if(!confirm('確定要刪除此使用者？'))return;try{await api('/api/users/'+id,{method:'DELETE'});toast('使用者已刪除');loadUsers();}catch(e){toast(e.message);}}
async function exportUsers(){const users=await api('/api/users');const rows=[['帳號','姓名','電話','電子郵件','角色','狀態','建立日期'],...users.map(u=>[u.account,u.name,u.phone,u.email,u.role,u.active?'啟用':'停用',u.created_at])];const csv=rows.map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv'}));a.download='safeguard-users.csv';a.click();URL.revokeObjectURL(a.href);}

let emailDeliveryFilter = 'all';

function formatEmailDeliveryTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return escapeHtml(value);
  return date.toLocaleString('zh-TW', {hour12:false});
}

function emailNotificationLabel(type) {
  return ({password_reset:'忘記密碼',test_email:'測試郵件',device_offline:'設備離線通知'})[type] || type || '系統通知';
}

async function loadEmailServiceStatus() {
  const status = await api('/api/email/status');
  const card = byId('emailServiceStatusCard');
  card.dataset.state = status.state;
  byId('emailServiceLabel').textContent = status.label;
  byId('emailServiceSender').textContent = status.sender;
  byId('emailServiceHost').textContent = `${status.host} : ${status.port}`;
  byId('emailServiceEncryption').textContent = status.encryption;
  byId('emailServiceLastCheck').textContent = formatEmailDeliveryTime(status.last_check);
}

async function loadEmailDeliveries() {
  const table = byId('emailDeliveryRows');
  try {
    const result = await api('/api/email/deliveries?status=' + encodeURIComponent(emailDeliveryFilter));
    const deliveries = result.deliveries || [];
    if (!deliveries.length) {
      table.innerHTML = '<tr><td colspan="6" class="email-delivery-empty">目前沒有符合條件的寄送紀錄</td></tr>';
      return;
    }
    table.innerHTML = deliveries.map(delivery => {
      const resultLabel = delivery.status === 'sent' ? '寄送成功' : delivery.status === 'failed' ? '寄送失敗' : '處理中';
      const retry = delivery.status === 'failed'
        ? `<button class="email-retry-button" type="button" onclick="retryEmailDelivery(${delivery.id},this)">✉ 重新傳送</button>`
        : '—';
      return `<tr>
        <td>${formatEmailDeliveryTime(delivery.sent_at || delivery.created_at)}</td>
        <td>${escapeHtml(delivery.recipient_masked)}</td>
        <td>${escapeHtml(emailNotificationLabel(delivery.notification_type))}</td>
        <td><span class="email-delivery-status ${escapeHtml(delivery.status)}">${resultLabel}</span></td>
        <td>${escapeHtml(delivery.failure_reason || '—')}</td>
        <td>${retry}</td>
      </tr>`;
    }).join('');
  } catch (error) {
    table.innerHTML = `<tr><td colspan="6" class="email-delivery-empty">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function loadEmailService() {
  try {
    await Promise.all([loadEmailServiceStatus(), loadEmailDeliveries()]);
  } catch (error) {
    toast(error.message);
  }
}

function setEmailDeliveryFilter(status, button) {
  emailDeliveryFilter = status;
  document.querySelectorAll('[data-email-status]').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  loadEmailDeliveries();
}

async function sendTestEmail(event) {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = '寄送中…';
  try {
    const result = await api('/api/email/test', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    toast(result.message);
  } catch (error) {
    toast('測試信失敗：' + error.message);
  } finally {
    button.disabled = false;
    button.textContent = '✉ 寄送測試信';
    loadEmailService();
  }
}

async function retryEmailDelivery(deliveryId, button) {
  button.disabled = true;
  button.textContent = '傳送中…';
  try {
    const result = await api(`/api/email/deliveries/${deliveryId}/retry`, {method:'POST'});
    toast(result.message);
  } catch (error) {
    toast('重新傳送失敗：' + error.message);
  } finally {
    loadEmailService();
  }
}

function openResetDialog(){byId('resetForm').reset();byId('resetDialog').showModal();}
async function requestPasswordReset(event){event.preventDefault();const body={account:byId('resetAccount').value,email:byId('resetEmail').value};try{const result=await api('/api/auth/request-password-reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});byId('resetDialog').close();toast(result.message||'若資料相符，重設連結已寄出');}catch(e){toast(e.message);}}

let yoloDevicesCache = [];
let yoloDeviceFilter = 'all';

async function loadYoloDevices() {
  try {
    yoloDevicesCache = await api('/api/monitoring-devices');
    renderYoloDevices();
  } catch (e) {
    const cards = byId('yoloDeviceCards');
    if (cards) cards.innerHTML = `<div class="yolo-empty-state">${escapeHtml(e.message)}</div>`;
  }
}

function setYoloDeviceFilter(filter, button) {
  yoloDeviceFilter = filter;
  document.querySelectorAll('.yolo-filters button').forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  renderYoloDevices();
}

function formatCameraLastSeen(value) {
  if (!value) return '尚未收到資料';
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return value;
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp.getTime()) / 1000));
  if (seconds < 60) return '剛剛';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分鐘前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小時前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function renderYoloDevices() {
  const cards = byId('yoloDeviceCards');
  if (!cards) return;
  const query = (byId('yoloDeviceSearch')?.value || '').trim().toLowerCase();
  const devices = yoloDevicesCache.filter(device => {
    const online = device.status === '正常';
    const filterMatch = yoloDeviceFilter === 'all' || (yoloDeviceFilter === 'online' ? online : !online);
    const searchMatch = !query || `${device.id} ${device.location}`.toLowerCase().includes(query);
    return filterMatch && searchMatch;
  });
  if (!devices.length) {
    cards.innerHTML = '<div class="yolo-empty-state">目前沒有符合條件的監控設備</div>';
    return;
  }
  cards.innerHTML = devices.map((device, index) => {
    const online = device.status === '正常';
    const offline = device.status === '離線';
    const previewText = online
      ? '監視器即時影像'
      : device.stream_url ? '點擊測試串流' : '尚未設定串流網址';
    return `
      <article class="yolo-device-card ${offline ? 'is-offline' : ''}">
        <div class="yolo-device-card-head">
          <div><span class="camera-symbol">▣</span><strong>${escapeHtml(device.id)}</strong><em></em><b>${escapeHtml(device.location)}</b></div>
          <span class="card-chevron">›</span>
        </div>
        <div class="yolo-device-meta">
          <span class="${online ? 'online' : 'offline'}"><i></i>${online ? '正常連線' : escapeHtml(device.status || '離線')}</span>
          <small>最後更新：${escapeHtml(formatCameraLastSeen(device.last_seen))}</small>
        </div>
        <div class="yolo-stream-url" title="${escapeHtml(device.stream_url || '尚未設定')}">
          <span>串流網址：</span>${device.stream_url ? escapeHtml(device.stream_url) : '<em>尚未設定</em>'}
        </div>
        <div class="camera-preview camera-preview-${index % 3}">
          <span class="camera-preview-icon">▣</span>
          <small>${previewText}</small>
        </div>
        <button onclick="enterYoloStream('${device.id}')">
          ${device.stream_url ? '進入 YOLO 串流' : '選擇設備'}
        </button>
      </article>
    `;
  }).join('');
}

function enterYoloStream(deviceId) {
  const device = yoloDevicesCache.find(item => item.id === deviceId);
  if (!device) return;
  byId('yoloDeviceSelection').hidden = true;
  byId('yoloStreamPanel').hidden = false;
  byId('selectedCameraTitle').textContent = `${device.id}｜${device.location}`;
  byId('videoSource').textContent = `${device.id}｜${device.location}`;
  const video = byId('streamVideo');
  video.pause();
  video.onloadeddata = null;
  video.onerror = null;
  video.removeAttribute('src');
  video.load();
  if (device.stream_url) {
    byId('streamPlaceholder').hidden = false;
    byId('streamPlaceholderText').textContent = '正在連線攝影機串流…';
    byId('streamStatus').textContent = '正在連線攝影機';
    byId('detectStatus').textContent = '等待影像來源';
    video.onloadeddata = () => {
      byId('streamPlaceholder').hidden = true;
      byId('streamStatus').textContent = '攝影機串流播放中';
      byId('detectStatus').textContent = '影像來源已連線（待串接 YOLO 模型）';
    };
    video.onerror = () => {
      byId('streamPlaceholder').hidden = false;
      byId('streamPlaceholderText').textContent = '無法播放此串流，請檢查網址與瀏覽器支援格式';
      byId('streamStatus').textContent = '攝影機串流連線失敗';
      byId('detectStatus').textContent = '影像來源未連線';
    };
    video.src = device.stream_url;
    video.play().catch(() => {});
  } else {
    byId('streamPlaceholder').hidden = false;
    byId('streamPlaceholderText').textContent = '此設備尚未設定串流網址，可至監控設備設定或上傳測試影片';
    byId('streamStatus').textContent = '設備已選擇，尚未設定串流網址';
    byId('detectStatus').textContent = '待機中';
  }
}

function backToYoloDevices() {
  const video = byId('streamVideo');
  video.pause();
  video.removeAttribute('src');
  video.load();
  byId('yoloStreamPanel').hidden = true;
  byId('yoloDeviceSelection').hidden = false;
}

async function loadVideos(){try{const data=await api('/api/videos');const select=byId('videoSelector');if(!select)return;const videos=Array.isArray(data)?data:(data.videos||[]);videos.forEach(v=>{const option=document.createElement('option');option.value=v.url;option.textContent=v.filename;select.appendChild(option);});}catch(e){toast(e.message);}}
async function uploadVideoFile(){const input=byId('videoUploadFile');if(!input.files.length)return;const form=new FormData();form.append('file',input.files[0]);try{const data=await api('/api/videos',{method:'POST',body:form});toast('影片已上傳');byId('videoSelector').innerHTML='<option value="">選擇已上傳影片</option>';await loadVideos();const options=[...byId('videoSelector').options];const video=options.find(o=>o.textContent===data.filename);if(video){video.selected=true;playSelectedVideo();}}catch(e){toast(e.message);}finally{input.value='';}}
function playSelectedVideo(){const select=byId('videoSelector');const video=byId('streamVideo');if(!select.value)return;video.src=select.value;video.play();byId('streamPlaceholder').hidden=true;byId('streamStatus').textContent='影片串流播放中';byId('detectStatus').textContent='影像來源已連線（待串接 YOLO 模型）';byId('videoSource').textContent=select.options[select.selectedIndex].textContent;}
