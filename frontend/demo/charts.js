/* Inline SVG charts. No dependency, no network fetch: the dashboard is served
   from the coordinator on a hackathon LAN and has to render offline. */
window.Charts = (() => {
  const SVG = 'http://www.w3.org/2000/svg';

  // Stable per-task-type colours so a type keeps its colour across renders.
  const TYPE_COLORS = {
    'summarization': '#5747ce',
    'document-qa': '#1f9d76',
    'information-extraction': '#d98324',
    'coding-assistance': '#c0457b'
  };
  // Machine colours are positional; the legend always spells out which is which.
  const SERIES = ['#5747ce', '#1f9d76', '#d98324', '#c0457b', '#3d8bd4', '#8a6fd4', '#7a8596'];

  const node = (name, attrs = {}) => {
    const element = document.createElementNS(SVG, name);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
    return element;
  };
  const colorFor = (index) => SERIES[index % SERIES.length];
  const percent = (value, total) => total ? Math.round((value / total) * 1000) / 10 : 0;

  /* Donut built from dash-offset arcs rather than path maths: exact at 100% and
     degrades cleanly when a slice rounds to nothing. */
  function donut(slices, {size = 190, thickness = 26, centerValue = '', centerLabel = ''} = {}) {
    const total = slices.reduce((sum, slice) => sum + slice.value, 0);
    const radius = (size - thickness) / 2;
    const circumference = 2 * Math.PI * radius;
    const svg = node('svg', {
      viewBox: `0 0 ${size} ${size}`, class: 'donut', role: 'img',
      'aria-label': total
        ? `Task share by machine: ${slices.map(s => `${s.label} ${s.value} (${percent(s.value, total)}%)`).join(', ')}`
        : 'No completed tasks yet'
    });
    const group = node('g', {transform: `rotate(-90 ${size / 2} ${size / 2})`});
    group.append(node('circle', {
      cx: size / 2, cy: size / 2, r: radius, fill: 'none',
      stroke: '#e6eaf3', 'stroke-width': thickness
    }));
    let offset = 0;
    // A visible gap only makes sense once there is more than one slice.
    const gap = slices.filter(slice => slice.value > 0).length > 1 ? 2 : 0;
    for (const [index, slice] of slices.entries()) {
      if (!slice.value) continue;
      const length = (slice.value / total) * circumference;
      group.append(node('circle', {
        cx: size / 2, cy: size / 2, r: radius, fill: 'none',
        stroke: slice.color || colorFor(index), 'stroke-width': thickness,
        'stroke-dasharray': `${Math.max(length - gap, 0.5)} ${circumference}`,
        'stroke-dashoffset': -offset, 'stroke-linecap': gap ? 'butt' : 'round',
        class: 'donut-slice'
      }));
      offset += length;
    }
    svg.append(group);
    if (centerValue !== '') {
      const value = node('text', {x: size / 2, y: size / 2 - 2, class: 'donut-value', 'text-anchor': 'middle'});
      value.textContent = String(centerValue);
      const caption = node('text', {x: size / 2, y: size / 2 + 18, class: 'donut-label', 'text-anchor': 'middle'});
      caption.textContent = centerLabel;
      svg.append(value, caption);
    }
    return svg;
  }

  /* One horizontal bar per machine, segmented by task type. Values are absolute so
     bar length compares machines directly rather than normalising each to 100%. */
  function stackedBar(segments, max) {
    const total = segments.reduce((sum, segment) => sum + segment.value, 0);
    const track = document.createElement('div');
    track.className = 'bar-track';
    const fill = document.createElement('div');
    fill.className = 'bar-fill';
    fill.style.width = `${max ? (total / max) * 100 : 0}%`;
    for (const segment of segments) {
      if (!segment.value) continue;
      const part = document.createElement('span');
      part.className = 'bar-segment';
      part.style.flexGrow = String(segment.value);
      part.style.background = segment.color || TYPE_COLORS[segment.type] || '#7a8596';
      part.title = `${segment.label}: ${segment.value}`;
      fill.append(part);
    }
    track.append(fill);
    return track;
  }

  // Sparkline of recent execution times, oldest to newest.
  function sparkline(values, {width = 132, height = 34} = {}) {
    const svg = node('svg', {
      viewBox: `0 0 ${width} ${height}`, class: 'sparkline', role: 'img',
      'aria-label': values.length ? `${values.length} recent execution times` : 'No timing history'
    });
    if (values.length < 2) return svg;
    const max = Math.max(...values), min = Math.min(...values);
    const span = max - min || 1;
    const points = values.map((value, index) => [
      (index / (values.length - 1)) * width,
      height - 3 - ((value - min) / span) * (height - 6)
    ]);
    svg.append(node('polyline', {
      points: points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' '),
      fill: 'none', stroke: '#5747ce', 'stroke-width': 2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round'
    }));
    const [lastX, lastY] = points[points.length - 1];
    svg.append(node('circle', {cx: lastX, cy: lastY, r: 2.6, fill: '#5747ce'}));
    return svg;
  }

  return {donut, stackedBar, sparkline, colorFor, percent, TYPE_COLORS, SERIES};
})();
