/* Local map assets only. Locations are fetched from this coordinator. */
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
    this.modelId = '';
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
  reload() { this.offset = 0; this.version++; this.refresh(); }
  choose(id) {
    this.selected = id;
    this.render();
    this.onChange();
  }
  setModel(modelId) { this.modelId = modelId; this.selected = ''; this.reload(); }
  setMode(mode) {
    this.mode = mode;
    this.selected = '';
    this.reload();
  }
  disconnect() {
    this.connected = false; this.version++; this.data = null; this.selected = '';
    document.getElementById('location-message').textContent = '';
    this.render();
  }
  async refresh() {
    if (!this.connected) return;
    const version = this.version;
    const query = new URLSearchParams({limit: '50', offset: String(this.offset), task_type: this.mode,
      gpu_only: String(document.getElementById('gpu-only').checked), online_only: String(document.getElementById('online-only').checked)});
    try {
      const data = await this.api('/workers/locations?' + query);
      if (!this.connected || version !== this.version) return;
      this.data = data;
      document.getElementById('location-message').textContent = '';
      this.render();
    } catch (error) {
      if (version === this.version && this.connected) document.getElementById('location-message').textContent = 'Worker locations unavailable. ' + error.message;
    }
  }
  render() {
    const list = document.getElementById('location-list');
    const scrollTop = list.scrollTop;
    const focusedWorker = list.contains(document.activeElement) ? document.activeElement.dataset.workerId : null;
    list.replaceChildren();
    const pins = document.getElementById('map-pins'); pins.replaceChildren();
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
    document.getElementById('distance-order').textContent = this.data?.distance_reference === 'coordinator'
      ? 'Closest to coordinator → furthest' : 'Distance unavailable';
    const groups = new Map();
    for (const item of items) {
      const w = item.worker;
      const models = w.models?.length ? w.models : [{model_id: w.model_id, supported_tasks: w.supported_tasks}];
      const compatible = this.modelId ? models.some(m => m.model_id === this.modelId && m.supported_tasks.includes(this.mode)) : item.compatible;
      const card = this.node('article', undefined, 'location-card' + (w.id === this.selected ? ' selected' : ''));
      const head = this.node('div', undefined, 'location-card-title');
      head.append(this.node('strong', w.name), this.node('span', w.status, 'site-status ' + w.status.toLowerCase()));
      card.append(head, this.node('p', w.location ? [w.location.site, w.location.region].filter(Boolean).join(' · ') : 'Location not shared', 'site-name'));
      card.append(this.node('p', `${w.gpu || 'GPU not reported'} · ${models.map(m => m.model_id).filter(Boolean).join(' · ') || 'No model reported'}`, 'site-hardware'));
      const revision = this.node('small', `Revision ${(w.model_revision || 'unknown').slice(0, 16)}`); revision.title = w.model_revision || ''; card.append(revision);
      const foot = this.node('div', undefined, 'location-card-title');
      foot.append(this.node('strong', item.distance_km === null ? 'Distance unavailable' : `${Math.round(item.distance_km).toLocaleString()} km away`, 'site-distance'));
      const button = this.node('button', w.id === this.selected ? 'Selected' : 'Use this worker', 'subtle');
      button.disabled = w.status === 'OFFLINE' || !compatible;
      button.setAttribute('aria-label', `Use worker ${w.name}`);
      button.dataset.workerId = w.id;
      button.setAttribute('aria-pressed', String(w.id === this.selected));
      button.onclick = () => this.choose(w.id);
      foot.append(button); card.append(foot);
      if (!compatible) card.append(this.node('small', 'Worker does not support the selected model, or its revision does not match the coordinator default.'));
      else if (w.status === 'BUSY') card.append(this.node('small', 'Busy — a selected job waits for this worker.'));
      list.append(card);
      if (w.location) {
        const key = `${w.location.latitude},${w.location.longitude}`;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(item);
      }
    }
    for (const group of groups.values()) {
      const w = group[0].worker;
      // Shared campus coordinates use a count pin. The list keeps each installation distinct.
      this.pin(w.location, group.map(item => item.worker.name).join(', '),
        group.every(item => item.worker.status === 'OFFLINE') ? 'offline' : 'available', () => {
          const cards = [...list.children];
          const index = items.findIndex(item => item.worker.id === w.id);
          cards[index]?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
          const first = cards[index]?.querySelector('button'); first?.focus();
        }, group.length > 1 ? String(group.length) : '');
    }
    if (!items.length) list.append(this.node('p', this.connected ? 'No workers match these filters. Try including offline or CPU machines.' : 'Connect to explore registered compute.', 'map-empty'));
    document.getElementById('map-caption').textContent = `${items.filter(item => item.worker.location).length} of ${items.length} machines on this page share a location. Unknown locations stay in the list.`;
    list.scrollTop = scrollTop;
    if (focusedWorker) [...list.querySelectorAll('button')].find(button => button.dataset.workerId === focusedWorker)?.focus({preventScroll: true});
  }
  pin(location, label, cls, onclick, text = '') {
    const pin = this.node(onclick ? 'button' : 'span', text, 'map-pin ' + cls);
    pin.style.left = `${(location.longitude + 180) / 360 * 100}%`;
    pin.style.top = `${(90 - location.latitude) / 180 * 100}%`;
    pin.title = label; pin.setAttribute('aria-label', label);
    if (onclick) pin.onclick = onclick;
    document.getElementById('map-pins').append(pin);
  }
};
