/**
 * Map view — Leaflet markers coloured by predicted risk.
 *
 * Basemap strategy, in order of preference:
 *   1. raster tiles (needs network) — full geographic context;
 *   2. a vendored GeoJSON of Cameroon's national and regional boundaries, drawn
 *      as vectors — works with no network at all;
 *   3. an inline SVG schematic, if Leaflet itself is unavailable.
 *
 * Levels 1 and 2 are drawn together: the vector boundaries sit above the tiles
 * at low fill opacity, so the map is legible whether or not tiles arrive. That
 * is why "no internet" no longer means "no map of Cameroon".
 */

import { MAP, REGION_GEO_NAMES } from '../config.js';
import { store } from '../state/store.js';
import { riskColor, decimal } from '../lib/format.js';
import { escapeHtml } from '../lib/dom.js';

const hasLeaflet = () => typeof globalThis.L !== 'undefined';

/** Boundary files are vendored next to the source, so resolve against this module. */
const geoUrl = (name) => new URL(`../data/${name}.json`, import.meta.url).href;

export function createMapView(container, { onSelect }) {
  let map = null;
  const markers = new Map();

  // Three distinct states. Conflating "not mounted yet" with "Leaflet failed"
  // was a real bug: a render scheduled during boot fires before mount(), and if
  // that render latched the fallback on, Leaflet was never used again even when
  // it had loaded perfectly.
  let mounted = false;
  let leafletFailed = false;

  let regionLayer = null;
  let tilesAlive = false;

  function incidenceFor(districtName) {
    const s = store.get();
    const forecast = s.forecasts[districtName];
    if (!forecast?.months?.length) return null;
    const month = forecast.months[s.selectedMonth] ?? forecast.months[0];
    return month?.predicted_incidence ?? null;
  }

  function thresholdFor(district) {
    return district.threshold;
  }

  // ── Leaflet path ───────────────────────────────────────────────────────────
  function initLeaflet() {
    const L = globalThis.L;
    map = L.map(container, { zoomControl: true, attributionControl: true })
      .setView(MAP.center, MAP.zoom);

    addTiles(L);
    void addBoundaries(L);

    // Leaflet measures its container once, at construction. Inside a CSS grid
    // the final size is often not settled at that moment, so the map renders
    // into a zero-height box and stays blank — the single most common cause of
    // "the map doesn't show up". Re-measure after layout, and on every resize.
    const refresh = () => map && map.invalidateSize({ animate: false });
    requestAnimationFrame(refresh);
    setTimeout(refresh, 200);

    if ('ResizeObserver' in globalThis) {
      new ResizeObserver(refresh).observe(container);
    } else {
      globalThis.addEventListener('resize', refresh);
    }
  }

  /**
   * Raster tiles, treated as a bonus rather than a requirement.
   *
   * A blocked or offline CDN otherwise leaves Leaflet drawing an empty grey
   * grid, which reads as "broken" even though the markers are fine. Dropping the
   * layer after repeated failures hands the job to the vector boundaries.
   */
  function addTiles(L) {
    let errors = 0;
    const tiles = L.tileLayer(MAP.tileUrl, {
      attribution: MAP.tileAttribution,
      minZoom: MAP.minZoom,
      maxZoom: MAP.maxZoom,
      // Upscale past the provider's deepest published level rather than asking
      // for tiles it does not have, which would look like an outage.
      maxNativeZoom: MAP.maxNativeZoom,
      crossOrigin: true,
    });

    // Place names, as a transparent overlay on the same provider.
    const labels = L.tileLayer(MAP.labelUrl, {
      minZoom: MAP.minZoom,
      maxZoom: MAP.maxZoom,
      maxNativeZoom: MAP.maxNativeZoom,
      crossOrigin: true,
    });

    tiles.on('tileload', () => { tilesAlive = true; });
    tiles.on('tileerror', () => {
      errors += 1;
      if (!tilesAlive && errors >= 4) {
        // Labels without a basemap under them read as floating text, so the two
        // are dropped together.
        map.removeLayer(tiles);
        map.removeLayer(labels);
        container.classList.add('map--vector-only');
        // Without tiles underneath, the boundaries carry the whole basemap and
        // need to be solid rather than a translucent overlay.
        styleRegions();
      }
    });

    tiles.addTo(map);
    labels.addTo(map);
  }

  /** Vendored Cameroon boundaries — the offline basemap. */
  async function addBoundaries(L) {
    try {
      const [adm0, adm1] = await Promise.all([
        fetch(geoUrl('cameroon_adm0')).then((r) => r.json()),
        fetch(geoUrl('cameroon_adm1')).then((r) => r.json()),
      ]);
      if (!map) return;

      regionLayer = L.geoJSON(adm1, {
        style: () => ({
          color: '#8b9a8f', weight: 1, fillColor: '#cfd9cd', fillOpacity: 0.28,
        }),
        // Non-interactive: clicks belong to the district markers on top.
        interactive: false,
      }).addTo(map);

      L.geoJSON(adm0, {
        style: () => ({ color: '#5a6b5f', weight: 2, fill: false }),
        interactive: false,
      }).addTo(map);

      // Boundaries are context, never the focus — keep them under the markers.
      regionLayer.bringToBack();
      styleRegions();
    } catch (err) {
      console.warn('[map] boundary data unavailable', err);
    }
  }

  /** Emphasise the filtered region, if any. */
  function styleRegions() {
    if (!regionLayer) return;
    const active = store.get().region;
    // Translucent over tiles so the geography shows through; opaque without
    // them, where the polygons are the only thing drawing the country.
    const base = tilesAlive ? 0.28 : 0.85;
    const hi = tilesAlive ? 0.45 : 0.95;

    regionLayer.eachLayer((layer) => {
      const geoName = layer.feature?.properties?.name;
      const dataName = REGION_GEO_NAMES[geoName] ?? geoName;
      const on = active && dataName === active;
      layer.setStyle(on
        ? { color: '#3a7d5d', weight: 2, fillColor: '#a9c6b2', fillOpacity: hi }
        : { color: '#8b9a8f', weight: 1, fillColor: '#e4eae1', fillOpacity: base });
    });
  }

  function syncMarkers(districts) {
    if (!map) return;
    const L = globalThis.L;
    const s = store.get();

    styleRegions();

    // Marker size and labelling have to adapt: 3 districts want big labelled
    // circles, 197 want small dots or the map becomes unreadable.
    const dense = districts.length > 25;
    const baseRadius = dense ? 7 : 16;

    // Drop markers for districts no longer displayed (region filter changed).
    const shown = new Set(districts.map((d) => d.name));
    for (const [name, marker] of markers) {
      if (!shown.has(name)) {
        map.removeLayer(marker);
        markers.delete(name);
      }
    }

    for (const district of districts) {
      const incidence = incidenceFor(district.name);
      const threshold = thresholdFor(district);
      const isSelected = district.name === s.selectedDistrict;
      const color = incidence == null ? '#9aa0a6' : riskColor(incidence, threshold);

      let marker = markers.get(district.name);
      if (!marker) {
        marker = L.circleMarker([district.lat, district.lon], {
          radius: baseRadius, color: '#fff', weight: 2, fillOpacity: 0.88,
        }).addTo(map);
        marker.on('click', () => onSelect(district.name));
        markers.set(district.name, marker);
      }

      // Permanent labels only when few enough to stay legible; otherwise the
      // name appears on hover.
      marker.unbindTooltip();
      marker.bindTooltip(district.name, dense
        ? { direction: 'top', offset: [0, -8], className: 'map-tip' }
        : { permanent: true, direction: 'top', offset: [0, -14], className: 'map-tip' });

      marker.setStyle({
        fillColor: color,
        weight: isSelected ? 4 : 2,
        radius: isSelected ? baseRadius + 5 : baseRadius,
      });

      marker.bindPopup(
        `<strong>${escapeHtml(district.name)}</strong>` +
        `<br><span style="color:#6b6657">${escapeHtml(district.region ?? '')}</span><br>` +
        (incidence == null
          ? 'No forecast yet'
          : `${decimal(incidence)} / 1000 &middot; threshold ${decimal(threshold)}`),
      );
    }

    // Refit whenever the displayed set changes, so switching region actually
    // moves the viewport instead of leaving the user over the previous area.
    const key = `${districts.length}:${districts[0]?.name ?? ''}`;
    if (districts.length && syncMarkers.lastKey !== key) {
      const bounds = L.latLngBounds(districts.map((d) => [d.lat, d.lon]));
      if (bounds.isValid()) {
        map.fitBounds(bounds.pad(districts.length > 1 ? 0.15 : 0.6));
      }
      syncMarkers.lastKey = key;
    }
  }

  // ── SVG fallback ───────────────────────────────────────────────────────────
  // Pure renderer: it must not mutate the component's state. Doing so is what
  // previously latched the dashboard into fallback mode permanently.
  function renderFallback(districts) {
    if (!districts.length) {
      container.innerHTML = '<div class="map-fallback-empty">No districts to display</div>';
      return;
    }

    const lats = districts.map((d) => d.lat);
    const lons = districts.map((d) => d.lon);
    const pad = 0.02;
    const minLat = Math.min(...lats) - pad;
    const maxLat = Math.max(...lats) + pad;
    const minLon = Math.min(...lons) - pad;
    const maxLon = Math.max(...lons) + pad;

    const W = 800;
    const H = 640;
    const x = (lon) => ((lon - minLon) / (maxLon - minLon || 1)) * (W - 160) + 80;
    // Latitude grows upward, SVG y grows downward.
    const y = (lat) => H - (((lat - minLat) / (maxLat - minLat || 1)) * (H - 160) + 80);

    const s = store.get();

    // Same density rule as the Leaflet path: 197 districts cannot carry
    // 24-pixel circles and permanent labels without becoming an unreadable pile.
    const dense = districts.length > 25;
    const r = dense ? 7 : 24;
    const rSel = dense ? 11 : 30;
    const showLabels = !dense;

    // Draw the selected district last so it is never buried under a neighbour.
    const ordered = [...districts].sort(
      (a, b) => (a.name === s.selectedDistrict ? 1 : 0)
              - (b.name === s.selectedDistrict ? 1 : 0));

    const nodes = ordered.map((d) => {
      const incidence = incidenceFor(d.name);
      const color = incidence == null ? '#9aa0a6' : riskColor(incidence, d.threshold);
      const selected = d.name === s.selectedDistrict;
      const cx = x(d.lon);
      const cy = y(d.lat);
      const label = showLabels
        ? `<text x="${cx}" y="${cy - (selected ? 40 : 34)}" text-anchor="middle"
                 class="fallback-label">${escapeHtml(d.name)}</text>
           <text x="${cx}" y="${cy + 5}" text-anchor="middle" class="fallback-value">
             ${incidence == null ? '—' : decimal(incidence)}
           </text>`
        // Dense mode: name on hover only, via the SVG native tooltip.
        : `<title>${escapeHtml(d.name)}${incidence == null ? ''
             : ` — ${decimal(incidence)}/1000`}</title>`;

      return `
        <g class="fallback-node" data-district="${escapeHtml(d.name)}" role="button"
           tabindex="0" aria-label="${escapeHtml(d.name)}">
          <circle cx="${cx}" cy="${cy}" r="${selected ? rSel : r}" fill="${color}"
                  stroke="#fff" stroke-width="${selected ? 3 : 1.5}" opacity="0.92"/>
          ${label}
        </g>`;
    }).join('');

    container.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" class="map-fallback" role="img"
           aria-label="Schematic district map">
        <rect width="${W}" height="${H}" fill="#e8ede9"/>
        <text x="${W / 2}" y="46" text-anchor="middle" class="fallback-title">
          Schematic view — Leaflet unavailable
        </text>
        ${nodes}
      </svg>`;

    container.querySelectorAll('.fallback-node').forEach((node) => {
      const name = node.dataset.district;
      node.addEventListener('click', () => onSelect(name));
      node.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(name); }
      });
    });
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  return {
    mount() {
      mounted = true;
      if (!hasLeaflet()) {
        leafletFailed = true;
        return;
      }
      try {
        initLeaflet();
      } catch (err) {
        console.warn('[map] Leaflet failed to initialise, using fallback', err);
        leafletFailed = true;
        map = null;
      }
    },

    render() {
      // Before mount() there is nothing to draw into. Rendering here would
      // stamp the container with markup that initLeaflet then has to fight.
      if (!mounted) return;
      const { districts } = store.get();
      if (map && !leafletFailed) syncMarkers(districts);
      else renderFallback(districts);
    },
  };
}
