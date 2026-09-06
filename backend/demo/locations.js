/* Leaflet is bundled locally; OpenStreetMap supplies visible map tiles. */
window.ComputeLocations = class {
  constructor(api, onChange) {
    this.api = api;
    this.onChange = onChange;
    this.data = null;
    this.selected = '';
    this.offset = 0;
    this.version = 0;
    this.connected = false;
    this.mode = 'summarization';
    this.origin = null;
    this.locationEpoch = 0;
    this.editEpoch = 0;
    this.resetView = true;
    this.initMap();
    document.getElementById('share-location').onclick = () => this.shareLocation();
    document.getElementById('choose-location').onclick = () => this.beginPick();
    document.getElementById('dismiss-location').onclick = () => {
      this.locationEpoch++;
      document.getElementById('share-location').disabled = false;
      document.getElementById('location-invite').hidden = true;
      document.getElementById('change-location').hidden = false;
    };
    document.getElementById('change-location').onclick = () => { document.getElementById('location-invite').hidden = false; document.getElementById('change-location').hidden = true; };
    document.getElementById('forget-location').onclick = () => this.forgetLocation();
    document.getElementById('fit-workers').onclick = () => this.fitMap();
    document.getElementById('save-map-location').onclick = () => this.savePickedLocation();
    document.getElementById('pick-map-center').onclick = () => this.map.fire('click', {latlng: this.map.getCenter()});
    document.getElementById('cancel-map-location').onclick = () => this.cancelPick();
    document.getElementById('site-name').oninput = () => this.validatePick();
    document.getElementById('worker-location-confirm').onchange = () => this.validatePick();
    for (const id of ['gpu-only', 'online-only']) document.getElementById(id).onchange = () => this.reload();
    document.getElementById('automatic-worker').onclick = () => this.choose('');
    document.getElementById('locations-prev').onclick = () => { this.offset = Math.max(0, this.offset - 50); this.version++; this.refresh(); };
    document.getElementById('locations-next').onclick = () => { this.offset += 50; this.version++; this.refresh(); };
  }
  node(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  reload() { this.offset = 0; this.version++; this.resetView = true; this.refresh(); }
  choose(id) {
    this.selected = id;
    this.render();
    this.onChange();
  }
  setMode(mode) {
    this.mode = mode;
    this.selected = '';
    this.reload();
  }
  disconnect() {
    this.connected = false; this.version++; this.data = null; this.selected = '';
    this.forgetLocation();
    this.cancelPick();
    document.getElementById('location-message').textContent = '';
    this.render();
  }
  async refresh() {
    if (!this.connected) return;
    const version = this.version;
    const query = new URLSearchParams({limit: '50', offset: String(this.offset), task_type: this.mode,
      gpu_only: String(document.getElementById('gpu-only').checked), online_only: String(document.getElementById('online-only').checked)});
    try {
      const data = this.origin
        ? await this.api('/workers/locations/search', {...this.origin, limit: 50, offset: this.offset,
          task_type: this.mode, gpu_only: document.getElementById('gpu-only').checked,
          online_only: document.getElementById('online-only').checked})
        : await this.api('/workers/locations?' + query);
      if (!this.connected || version !== this.version) return;
      this.data = data;
      document.getElementById('location-message').textContent = '';
      this.render();
    } catch (error) {
      if (version === this.version && this.connected) document.getElementById('location-message').textContent = 'Worker map unavailable. ' + (error.status === 404 ? 'The coordinator is running an older backend. Its owner must update the code and restart it.' : error.message);
    }
  }
  render() {
    const list = document.getElementById('location-list');
    const scrollTop = list.scrollTop;
    const focusedWorker = list.contains(document.activeElement) ? document.activeElement.dataset.workerId : null;
    list.replaceChildren();
    const items = this.data?.items || [];
    const selected = items.find(item => item.worker.id === this.selected);
    document.getElementById('selected-worker').textContent = this.selected
      ? `Selected: ${selected?.worker.name || this.selected.slice(0, 8)}. This job waits for this machine if it disconnects.`
      : 'Automatic: any online worker with the matching model can claim your job.';
    document.getElementById('automatic-worker').setAttribute('aria-pressed', String(!this.selected));
    const total = this.data?.total || 0;
    document.getElementById('locations-count').textContent = `${total} matching machines`;
    document.getElementById('locations-page').textContent = total ? `${this.offset + 1}–${this.offset + items.length} of ${total}` : '0 machines';
    document.getElementById('locations-prev').disabled = this.offset === 0;
    document.getElementById('locations-next').disabled = this.offset + items.length >= total;
    document.getElementById('distance-order').textContent = this.data?.distance_reference === 'request'
      ? 'Closest to you → furthest' : this.data?.distance_reference === 'coordinator'
        ? 'Closest to coordinator → furthest' : 'Share location to compare distance';
    for (const item of items) {
      const w = item.worker;
      const card = this.node('article', undefined, 'location-card' + (w.id === this.selected ? ' selected' : ''));
      const head = this.node('div', undefined, 'location-card-title');
      head.append(this.node('strong', w.name), this.node('span', w.status, 'site-status ' + w.status.toLowerCase()));
      card.append(head, this.node('p', w.location ? [w.location.site, w.location.region].filter(Boolean).join(' · ') : 'Location not shared', 'site-name'));
      card.append(this.node('p', `${w.gpu || 'GPU not reported'} · ${w.model_id || 'No model reported'}`, 'site-hardware'));
      const revision = this.node('small', `Revision ${(w.model_revision || 'unknown').slice(0, 16)}`); revision.title = w.model_revision || ''; card.append(revision);
      const foot = this.node('div', undefined, 'location-card-title');
      foot.append(this.node('strong', item.distance_km === null ? 'Distance unavailable' : `${Math.round(item.distance_km).toLocaleString()} km away`, 'site-distance'));
      const button = this.node('button', w.id === this.selected ? 'Selected' : 'Use this worker', 'subtle');
      button.disabled = w.status === 'OFFLINE' || !item.compatible;
      button.setAttribute('aria-label', `Use worker ${w.name}`);
      button.dataset.workerId = w.id;
      button.setAttribute('aria-pressed', String(w.id === this.selected));
      button.onclick = () => this.choose(w.id);
      foot.append(button); card.append(foot);
      if (!item.compatible) card.append(this.node('small', 'Model revision does not match the coordinator.'));
      else if (w.status === 'BUSY') card.append(this.node('small', 'Busy — a selected job waits for this worker.'));
      const place = this.node('button', w.location ? 'Edit map location' : 'Place this worker on map', 'subtle');
      place.setAttribute('aria-label', `Set location for ${w.name}`);
      place.onclick = () => this.beginPick(w);
      card.append(place);
      list.append(card);
    }
    this.renderMap(items);
    if (!items.length) list.append(this.node('p', this.connected ? 'No workers match these filters. Try including offline or CPU machines.' : 'Connect to explore registered compute.', 'map-empty'));
    document.getElementById('map-caption').textContent = `${items.filter(item => item.worker.location).length} of ${items.length} machines on this page share a location. For a missing pin, the worker owner can use ‘Place this worker on map’. Sharing your area only changes distance estimates.`;
    list.scrollTop = scrollTop;
    if (focusedWorker) [...list.querySelectorAll('button')].find(button => button.dataset.workerId === focusedWorker)?.focus({preventScroll: true});
  }
  initMap() {
    this.map = L.map('compute-map', {worldCopyJump: true, minZoom: 0, maxZoom: 19}).setView([25, 0], 2);
    this.tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(this.map);
    this.tiles.on('tileerror', () => {
      document.getElementById('tile-message').textContent = 'Map tiles could not load. Check internet access; worker locations remain available in the list.';
    });
    this.workerLayer = L.layerGroup().addTo(this.map);
    this.originLayer = L.layerGroup().addTo(this.map);
    this.pickLayer = L.layerGroup().addTo(this.map);
    this.map.on('click', event => {
      if (!this.editing) return;
      const point = event.latlng.wrap();
      this.candidate = {latitude: Number(point.lat.toFixed(2)), longitude: Number(point.lng.toFixed(2))};
      this.pickLayer.clearLayers();
      this.marker(this.candidate, 'Chosen area', 'chosen').addTo(this.pickLayer);
      document.getElementById('map-edit-help').textContent = this.editWorker
        ? `Area selected for ${this.editWorker.name}. Confirm the worker location below, then save.`
        : 'Area selected. Use this approximate location for distance estimates?';
      this.validatePick();
    });
  }
  marker(location, label, cls, text = '') {
    const icon = this.node('span', text, 'compute-pin-dot ' + cls);
    return L.marker([location.latitude, location.longitude], {
      title: label, alt: label, keyboard: true,
      icon: L.divIcon({className: 'compute-pin', html: icon, iconSize: [24, 24], iconAnchor: [12, 12]})
    });
  }
  renderMap(items) {
    const signature = JSON.stringify([items.map(({worker: w}) => [w.id, w.name, w.status, w.location]), this.origin]);
    if (signature === this.mapSignature) {
      if (this.resetView && !this.editing) { this.fitMap(); this.resetView = false; }
      return;
    }
    this.mapSignature = signature;
    this.workerLayer.clearLayers(); this.originLayer.clearLayers();
    const groups = new Map();
    for (const {worker} of items) {
      if (!worker.location) continue;
      const key = `${worker.location.latitude},${worker.location.longitude}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(worker);
    }
    for (const workers of groups.values()) {
      const first = workers[0];
      const popup = this.node('div');
      popup.append(this.node('strong', first.location.site));
      for (const worker of workers) {
        const button = this.node('button', `${worker.name} · ${worker.status}`, 'subtle');
        button.onclick = () => {
          const card = [...document.querySelectorAll('.location-card')].find(card => card.querySelector('[data-worker-id]')?.dataset.workerId === worker.id);
          card?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
          card?.querySelector('[data-worker-id]')?.focus({preventScroll: true});
        };
        popup.append(button);
      }
      this.marker(first.location, workers.map(w => w.name).join(', '), workers.every(w => w.status === 'OFFLINE') ? 'offline' : 'online', workers.length > 1 ? String(workers.length) : '')
        .bindPopup(popup).addTo(this.workerLayer);
    }
    if (this.origin) this.marker(this.origin, 'Your shared area', 'visitor').addTo(this.originLayer);
    if (this.resetView && !this.editing && (groups.size || this.origin)) { this.fitMap(); this.resetView = false; }
  }
  fitMap() {
    const points = (this.data?.items || []).filter(item => item.worker.location)
      .map(item => [item.worker.location.latitude, item.worker.location.longitude]);
    if (this.origin) points.push([this.origin.latitude, this.origin.longitude]);
    if (points.length) this.map.fitBounds(points, {padding: [30, 30], maxZoom: 12, animate: false});
  }
  shareLocation() {
    const epoch = ++this.locationEpoch;
    const message = document.getElementById('visitor-location-message');
    if (!window.isSecureContext) {
      message.textContent = 'Automatic location needs HTTPS on this network address. Choose your area on the map, or ask the host for an HTTPS link.';
      return;
    }
    if (!navigator.geolocation) { message.textContent = 'Location is unavailable in this browser. Choose your area on the map.'; return; }
    document.getElementById('share-location').disabled = true;
    message.textContent = 'Waiting for your browser location permission…';
    navigator.geolocation.getCurrentPosition(position => {
      if (epoch !== this.locationEpoch) return;
      document.getElementById('share-location').disabled = false;
      this.useOrigin({latitude: Number(position.coords.latitude.toFixed(2)), longitude: Number(position.coords.longitude.toFixed(2))});
    }, error => {
      if (epoch !== this.locationEpoch) return;
      document.getElementById('share-location').disabled = false;
      message.textContent = error.code === 1 ? 'Location permission was denied. You can still choose an area on the map.' : 'Your location could not be found. Try again or choose an area on the map.';
    }, {enableHighAccuracy: false, timeout: 10000, maximumAge: 60000});
  }
  useOrigin(origin) {
    this.origin = origin;
    document.getElementById('location-invite').hidden = true;
    document.getElementById('forget-location').hidden = false;
    document.getElementById('change-location').hidden = false;
    document.getElementById('change-location').textContent = 'Change your area';
    document.getElementById('visitor-location-message').textContent = 'Your approximate area is shared for this page. Distance estimates are calculated by the coordinator.';
    this.reload();
    this.renderMap(this.data?.items || []);
  }
  forgetLocation() {
    this.locationEpoch++;
    this.origin = null;
    document.getElementById('share-location').disabled = false;
    document.getElementById('forget-location').hidden = true;
    document.getElementById('change-location').textContent = 'Share location';
    document.getElementById('visitor-location-message').textContent = '';
    this.reload();
    this.renderMap(this.data?.items || []);
  }
  beginPick(worker = null) {
    this.locationEpoch++;
    document.getElementById('share-location').disabled = false;
    this.cancelPick(); this.editing = true; this.editWorker = worker;
    document.getElementById('map-location-editor').hidden = false;
    document.getElementById('site-name-field').hidden = !worker;
    document.getElementById('worker-location-confirm-field').hidden = !worker;
    document.getElementById('worker-location-confirm').checked = false;
    document.getElementById('site-name').value = worker?.location?.site || '';
    document.getElementById('map-edit-help').textContent = worker
      ? `Pan and zoom, then click where ${worker.name} is physically located. Only set locations for workers you manage.`
      : 'Pan and zoom to your approximate area, then click the map.';
    document.getElementById('save-map-location').textContent = worker ? 'Save worker location' : 'Use this area';
    document.getElementById('compute-map').classList.add('picking-location');
    document.getElementById('compute-map').scrollIntoView({behavior: 'smooth', block: 'center'});
  }
  validatePick() {
    document.getElementById('save-map-location').disabled = this.saving || !this.candidate || (this.editWorker &&
      (!document.getElementById('worker-location-confirm').checked || !document.getElementById('site-name').value.trim()));
  }
  cancelPick() {
    this.editEpoch++; this.editing = false; this.editWorker = null; this.candidate = null; this.saving = false;
    this.pickLayer.clearLayers();
    document.getElementById('map-location-editor').hidden = true;
    document.getElementById('save-map-location').disabled = true;
    document.getElementById('compute-map').classList.remove('picking-location');
  }
  async savePickedLocation() {
    if (!this.candidate || this.saving) return;
    if (!this.editWorker) { const origin = this.candidate; this.cancelPick(); this.useOrigin(origin); return; }
    if (!this.connected || !document.getElementById('worker-location-confirm').checked) return;
    const site = document.getElementById('site-name').value.trim();
    if (!site) return;
    const epoch = this.editEpoch;
    this.saving = true; this.validatePick();
    try {
      await this.api(`/workers/${this.editWorker.id}/location`, {location: {site, ...this.candidate}});
      if (epoch !== this.editEpoch) return;
      this.cancelPick(); this.reload();
    } catch (error) {
      if (epoch === this.editEpoch) {
        this.saving = false; this.validatePick();
        document.getElementById('map-edit-help').textContent = 'Location was not saved. ' + error.message;
      }
    }
  }
};
