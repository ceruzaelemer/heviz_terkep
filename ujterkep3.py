import psycopg2
import pandas as pd
from pyproj import Transformer
import json
import math
import traceback
from pathlib import Path
from datetime import datetime

def groupby_to_dict(df_sub, id_col):
    """Pandas-verzió-független groupby helper."""
    result = {}
    for key, group in df_sub.groupby(id_col):
        result[key] = group.drop(columns=[id_col]).to_dict(orient="records")
    return result

try:
    # 1) Adatbázis kapcsolat
    print("Adatbazishoz csatlakozas...")
    conn = psycopg2.connect(
        host="localhost",
        database="heviz_adatbazis",
        user="postgres",
        password="vacKor16",
        port="5432"
    )
    print("  OK")

    # 2) Alap adatok beolvasása
    print("Kutak_raw beolvasasa...")
    df = pd.read_sql_query("SELECT * FROM kutak_raw;", conn)
    print(f"  {len(df)} sor beolvasva")

    # Csövezés
    print("Csovezes beolvasasa...")
    csov = pd.read_sql_query(
        "SELECT kut_azonosito, atmero_mm, melyseg_tol_m, melyseg_ig_m FROM csovezes;",
        conn
    ).fillna("").astype(str)
    csov_grouped = groupby_to_dict(csov, "kut_azonosito")
    df["csovezes"] = df["kut_azonosito"].apply(lambda k: csov_grouped.get(k, []))
    print(f"  OK")

    # Szűrés
    print("Szuro beolvasasa...")
    szuro = pd.read_sql_query(
        "SELECT kut_azonosito, atmero_mm, melyseg_tol_m, melyseg_ig_m FROM szuro;",
        conn
    ).fillna("").astype(str)
    szuro_grouped = groupby_to_dict(szuro, "kut_azonosito")
    df["szurozes"] = df["kut_azonosito"].apply(lambda k: szuro_grouped.get(k, []))
    print(f"  OK")

    # Víztermelés
    print("Viztermeles beolvasasa...")
    viz = pd.read_sql_query(
        "SELECT kut_azonosito, vizhozam_l_p, vizszint_m FROM viztermeles;",
        conn
    ).fillna("").astype(str)
    viz_grouped = groupby_to_dict(viz, "kut_azonosito")
    df["viztermeles"] = df["kut_azonosito"].apply(lambda k: viz_grouped.get(k, []))
    print(f"  OK")

    # Kémiai adatok
    print("Kemia beolvasasa...")
    kemia = pd.read_sql_query("SELECT * FROM kut_kemia2;", conn).fillna("").astype(str)
    kemia_grouped = groupby_to_dict(kemia, "kut_azonosito")
    df["kemia"] = df["kut_azonosito"].apply(lambda k: kemia_grouped.get(k, []))
    print(f"  OK")

    conn.close()

    # EOV tisztítás és konverzió
    print("Koordinata-konverzio (EOV -> WGS84)...")
    def clean_eov(value):
        try:
            return float(str(value).replace(",", "."))
        except:
            return None

    df["eov_x_clean"] = df["eov_x"].apply(clean_eov)
    df["eov_y_clean"] = df["eov_y"].apply(clean_eov)

    transformer = Transformer.from_crs("EPSG:23700", "EPSG:4326", always_xy=True)
    def convert_eov_to_wgs(x, y):
        if x is None or y is None:
            return None, None
        lon, lat = transformer.transform(y, x)
        return lat, lon

    df["lat"], df["lon"] = zip(*df.apply(
        lambda r: convert_eov_to_wgs(r["eov_x_clean"], r["eov_y_clean"]), axis=1
    ))
    print("  OK")

    # NaN -> None konverzió
    print("JSON elokeszites...")
    def clean_nan(obj):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: clean_nan(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [clean_nan(item) for item in obj]
        return obj

    records = clean_nan(df.to_dict(orient="records"))
    kutak_json = json.dumps(records, ensure_ascii=False, allow_nan=False)
    kutak_json_safe = kutak_json.replace("</", "<\\/")
    print("  OK")

except Exception as e:
    print("")
    print("=" * 60)
    print("HIBA TORTENT!")
    print("-" * 60)
    traceback.print_exc()
    print("=" * 60)
    input("\nNyomj Entert a bezarashoz...")
    exit(1)

# ---------------------------------------------------------------
# HTML: az összes JS-t külön változóban tároljuk, hogy elkerüljük
# az f-string idézőjel-escape problémáját az onclick-ekben.
# Megoldás: data-kutid attribútumok + jQuery eseménydelegálás.
# ---------------------------------------------------------------

JS_CODE = r"""
const adatok = __ADATOK_PLACEHOLDER__;

// Aktuális dátum generálása (MMDD formátumban)
function getDateString() {
    var now = new Date();
    var month = String(now.getMonth() + 1).padStart(2, '0');
    var day = String(now.getDate()).padStart(2, '0');
    return month + day;
}

// --- Térkép ---
const map = L.map('map').setView([47.0, 19.7], 7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const redIcon = L.divIcon({
    html: '<div style="width:8px;height:8px;background:#e53935;border-radius:50%;"></div>',
    iconSize: [8, 8], className: ''
});
const yellowIcon = L.divIcon({
    html: '<div style="width:13px;height:13px;background:#fdd835;border-radius:50%;border:2px solid #f57f17;"></div>',
    iconSize: [13, 13], className: ''
});

const markers = {};
adatok.forEach(function(kut) {
    try {
        if (!kut.lat || !kut.lon) return;
        const lat = parseFloat(kut.lat);
        const lon = parseFloat(kut.lon);
        if (isNaN(lat) || isNaN(lon)) return;
        const marker = L.marker([lat, lon], { icon: redIcon }).addTo(map);
        markers[kut.kut_azonosito] = marker;
        // data-kutid attribútum a popupban – nincs idézőjel-escape probléma
        const popupHtml =
            '<strong>' + (kut.kut_azonosito || '') + '</strong><br>' +
            '<b>Megnevezés:</b> ' + (kut.kut_megnevezes || '-') + '<br>' +
            '<b>Település:</b> ' + (kut.telepules || '-') + '<br>' +
            '<b>Kataszteri szám:</b> ' + (kut.hevizkut_kataszteri_szam || '-') + '<br>' +
            '<b>VIFIR kód:</b> ' + (kut.vifir_kod || '-') + '<br>' +
            '<b>Építés éve:</b> ' + (kut.epites_eve || '-') + '<br><br>' +
            '<a href="#" class="popup-open-panel" data-kutid="' + kut.kut_azonosito + '">Részletek megnyitása</a>';
        marker.bindPopup(popupHtml);
        marker.on('click', (function(id) { return function() { openPanel(id); }; })(kut.kut_azonosito));
    } catch(e) { console.error('Marker hiba:', kut.kut_azonosito, e); }
});

// Popup kattintás eseménydelegálással (Leaflet popupok a document alatt vannak)
$(document).on('click', '.popup-open-panel', function(e) {
    e.preventDefault();
    openPanel($(this).data('kutid'));
});

function resetAllMarkers() {
    Object.values(markers).forEach(function(m) { m.setIcon(redIcon); });
}
function highlightMarkers(ids) {
    resetAllMarkers();
    var bounds = [];
    ids.forEach(function(id) {
        if (markers[id]) { markers[id].setIcon(yellowIcon); bounds.push(markers[id].getLatLng()); }
    });
    if (bounds.length === 1) { map.setView(bounds[0], 13); }
    else if (bounds.length > 1) { map.fitBounds(L.latLngBounds(bounds), { padding: [40, 40] }); }
}
function highlightRow(kutId) {
    $('#kutTable tbody tr').removeClass('highlight-row');
    $('#kutTable tbody tr').each(function() {
        if ($(this).find('td').eq(1).text().trim() === kutId) $(this).addClass('highlight-row');
    });
}

// --- Normalizálás ---
function normalize(str) {
    return String(str === null || str === undefined ? '' : str)
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
}
var SEARCH_FIELDS = ['kut_azonosito','kut_megnevezes','hevizkut_kataszteri_szam','vifir_kod','epites_eve','telepules'];
function matchesSearch(kut, term) {
    if (!term) return true;
    var n = normalize(term);
    return SEARCH_FIELDS.some(function(f) { return normalize(kut[f]).indexOf(n) !== -1; });
}

// --- Szűrők ---
var activeSearch = '', filterTelepules = '', filterEvTol = null, filterEvIg = null;
var filterVanKemia = false, filterVanViz = false;

function matchesFilters(kut) {
    if (!matchesSearch(kut, activeSearch)) return false;
    if (filterTelepules && normalize(kut.telepules) !== normalize(filterTelepules)) return false;
    if (filterEvTol !== null) { var ev = parseInt(kut.epites_eve); if (isNaN(ev) || ev < filterEvTol) return false; }
    if (filterEvIg !== null) { var ev2 = parseInt(kut.epites_eve); if (isNaN(ev2) || ev2 > filterEvIg) return false; }
    if (filterVanKemia && (!kut.kemia || kut.kemia.length === 0)) return false;
    if (filterVanViz && (!kut.viztermeles || kut.viztermeles.length === 0)) return false;
    return true;
}

$.fn.dataTable.ext.search.push(function(settings, data, dataIndex, rowData) {
    if (!rowData) return true;
    return matchesFilters(rowData);
});

// --- DataTable ---
// FONTOS: data-kutid attribútumokat használunk onclick helyett,
// így elkerüljük az idézőjel-problémákat.
var table = $('#kutTable').DataTable({
    data: adatok,
    columns: [
        {
            data: null, orderable: false, searchable: false,
            render: function(data, type, row) {
                var id = (row && row.kut_azonosito) ? row.kut_azonosito : '';
                return '<input type="checkbox" class="rowCheck" data-kutid="' + id + '" />';
            }
        },
        {
            data: 'kut_azonosito', defaultContent: '',
            render: function(id) {
                if (!id) return '';
                return '<a href="#" class="kut-id-link" data-kutid="' + id + '">' + id + '</a>';
            }
        },
        { data: 'hevizkut_kataszteri_szam', defaultContent: '' },
        { data: 'vifir_kod', defaultContent: '' },
        { data: 'epites_eve', defaultContent: '' },
        {
            data: 'kut_azonosito', orderable: false, defaultContent: '',
            render: function(id) {
                if (!id) return '';
                return '<button class="kut-detail-btn" data-kutid="' + id + '">Részletek</button>';
            }
        }
    ],
    pageLength: 10, lengthChange: false,
    language: { search: '', searchPlaceholder: 'Szűrés a listában...' }
});

// Eseménydelegálás a táblázat linkjeire és gombjára
$(document).on('click', '.kut-id-link', function(e) {
    e.preventDefault();
    var id = $(this).data('kutid');
    highlightMarkers([id]);
    highlightRow(id);
});
$(document).on('click', '.kut-detail-btn', function() {
    var id = $(this).data('kutid');
    showDetailView();
    buildDetailTable(id);
    highlightMarkers([id]);
    highlightRow(id);
});

table.on('draw', function() {
    var hasFilter = activeSearch || filterTelepules || filterEvTol !== null || filterEvIg !== null || filterVanKemia || filterVanViz;
    if (hasFilter) {
        var ids = table.rows({ filter: 'applied' }).data().toArray().map(function(r) { return r.kut_azonosito; });
        highlightMarkers(ids);
    } else { resetAllMarkers(); }
    var total = table.rows({ filter: 'applied' }).count();
    document.getElementById('searchInfo').textContent = total < adatok.length ? total + ' talalat' : '';
});

// --- Keresés + autocomplete ---
var searchInput = document.getElementById('searchInput');
var autocompleteList = document.getElementById('autocompleteList');

function applySearch(term) {
    activeSearch = term; table.draw(); updateUrl();
    autocompleteList.style.display = 'none';
}
document.getElementById('searchBtn').addEventListener('click', function() {
    applySearch(searchInput.value.trim()); openSidePanel();
});
searchInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') { applySearch(searchInput.value.trim()); openSidePanel(); }
});
searchInput.addEventListener('input', function() {
    var term = this.value.trim();
    if (term.length < 2) { autocompleteList.style.display = 'none'; return; }
    var n = normalize(term), suggestions = [];
    for (var i = 0; i < adatok.length && suggestions.length < 10; i++) {
        var k = adatok[i];
        if (SEARCH_FIELDS.some(function(f) { return normalize(k[f]).indexOf(n) !== -1; })) {
            var label = k.kut_azonosito || '';
            if (k.kut_megnevezes) label += ' - ' + k.kut_megnevezes;
            if (k.telepules) label += ' (' + k.telepules + ')';
            suggestions.push({ id: k.kut_azonosito, label: label });
        }
    }
    if (!suggestions.length) { autocompleteList.style.display = 'none'; return; }
    // data-kutid a legördülőben is
    autocompleteList.innerHTML = suggestions.map(function(s) {
        return '<div class="ac-item" data-kutid="' + s.id + '">' + s.label + '</div>';
    }).join('');
    autocompleteList.style.display = 'block';
});
$(document).on('click', '.ac-item', function() {
    var id = $(this).data('kutid');
    searchInput.value = id;
    autocompleteList.style.display = 'none';
    applySearch(id); openSidePanel();
});
document.addEventListener('click', function(e) {
    if (!e.target.closest('#searchWrapper')) autocompleteList.style.display = 'none';
});

// --- Szűrőpanel ---
var telepulesek = [];
adatok.forEach(function(k) {
    if (k.telepules && k.telepules.trim() && telepulesek.indexOf(k.telepules) === -1) telepulesek.push(k.telepules);
});
telepulesek.sort();
var filterTelepulesEl = document.getElementById('filterTelepules');
telepulesek.forEach(function(t) {
    var o = document.createElement('option'); o.value = t; o.textContent = t; filterTelepulesEl.appendChild(o);
});
document.getElementById('filterToggleBtn').addEventListener('click', function() {
    var fp = document.getElementById('filterPanel');
    fp.style.display = fp.style.display === 'flex' ? 'none' : 'flex';
});
filterTelepulesEl.addEventListener('change', function() { filterTelepules = this.value; table.draw(); updateUrl(); });
document.getElementById('filterEvTol').addEventListener('input', function() { filterEvTol = this.value ? parseInt(this.value) : null; table.draw(); updateUrl(); });
document.getElementById('filterEvIg').addEventListener('input', function() { filterEvIg = this.value ? parseInt(this.value) : null; table.draw(); updateUrl(); });
document.getElementById('filterVanKemia').addEventListener('change', function() { filterVanKemia = this.checked; table.draw(); updateUrl(); });
document.getElementById('filterVanViz').addEventListener('change', function() { filterVanViz = this.checked; table.draw(); updateUrl(); });
document.getElementById('clearFiltersBtn').addEventListener('click', function() {
    filterTelepules=''; filterEvTol=null; filterEvIg=null; filterVanKemia=false; filterVanViz=false; activeSearch='';
    filterTelepulesEl.value='';
    document.getElementById('filterEvTol').value='';
    document.getElementById('filterEvIg').value='';
    document.getElementById('filterVanKemia').checked=false;
    document.getElementById('filterVanViz').checked=false;
    searchInput.value=''; table.draw(); updateUrl();
});

// --- URL megosztás ---
function updateUrl() {
    var params = new URLSearchParams();
    if (activeSearch) params.set('kut', activeSearch);
    if (filterTelepules) params.set('telepules', filterTelepules);
    if (filterEvTol !== null) params.set('ev_tol', filterEvTol);
    if (filterEvIg !== null) params.set('ev_ig', filterEvIg);
    if (filterVanKemia) params.set('van_kemia', '1');
    if (filterVanViz) params.set('van_viz', '1');
    var qs = params.toString();
    history.replaceState(null, '', qs ? '?' + qs : window.location.pathname);
}
function loadFromUrl() {
    var params = new URLSearchParams(window.location.search);
    if (params.has('kut')) { searchInput.value = params.get('kut'); activeSearch = params.get('kut'); }
    if (params.has('telepules')) { filterTelepules = params.get('telepules'); filterTelepulesEl.value = filterTelepules; }
    if (params.has('ev_tol')) { filterEvTol = parseInt(params.get('ev_tol')); document.getElementById('filterEvTol').value = filterEvTol; }
    if (params.has('ev_ig')) { filterEvIg = parseInt(params.get('ev_ig')); document.getElementById('filterEvIg').value = filterEvIg; }
    if (params.get('van_kemia') === '1') { filterVanKemia = true; document.getElementById('filterVanKemia').checked = true; }
    if (params.get('van_viz') === '1') { filterVanViz = true; document.getElementById('filterVanViz').checked = true; }
    if (activeSearch || filterTelepules || filterEvTol !== null || filterEvIg !== null || filterVanKemia || filterVanViz) {
        table.draw(); openSidePanel();
    }
}

// --- Oldalpanel ---
function openSidePanel() { document.getElementById('sidePanel').classList.add('open'); showListView(); }
function openPanel(kutId) { openSidePanel(); highlightMarkers([kutId]); highlightRow(kutId); }
document.getElementById('closePanel').onclick = function() {
    document.getElementById('sidePanel').classList.remove('open');
    resetAllMarkers(); $('#kutTable tbody tr').removeClass('highlight-row');
};
function showListView() { document.getElementById('listView').style.display='block'; document.getElementById('detailView').style.display='none'; }
function showDetailView() { document.getElementById('listView').style.display='none'; document.getElementById('detailView').style.display='block'; }
document.getElementById('backToList').onclick = function() { showListView(); };

// --- Checkbox + export ---
var selectAllMode = false;
document.getElementById('selectAllBtn').addEventListener('click', function() {
    selectAllMode = !selectAllMode;
    $('#kutTable tbody input.rowCheck').prop('checked', selectAllMode);
    document.getElementById('masterCheck').checked = selectAllMode;
    this.textContent = selectAllMode ? 'Kijololes torlese' : 'Osszes kijelolese';
});
document.getElementById('masterCheck').addEventListener('change', function() {
    $('#kutTable tbody input.rowCheck').prop('checked', this.checked);
});
function getSelectedData() {
    var checked = [];
    $('#kutTable tbody input.rowCheck:checked').each(function() {
        var id = $(this).data('kutid');
        var kut = adatok.find(function(k) { return k.kut_azonosito === id; });
        if (kut) checked.push(kut);
    });
    return checked.length ? checked : table.rows({ filter: 'applied' }).data().toArray();
}

// Beágyazott tömb-mezők, amelyek külön fülre kerülnek
var NESTED_KEYS = ['csovezes', 'szurozes', 'viztermeles', 'kemia', 'eov_x_clean', 'eov_y_clean'];

// Összes alapadat-mező dinamikusan (az első rekordból)
function getAlapadatFields() {
    if (!adatok.length) return [];
    return Object.keys(adatok[0]).filter(function(k) { return NESTED_KEYS.indexOf(k) === -1; });
}

// Dinamikus sorok építése: minden meglévő oszlopot figyelembe vesz
function buildFlatRows(data, nestedKey) {
    // Gyűjtsük össze az összes előforduló oszlopnevet
    var colSet = {};
    data.forEach(function(k) {
        (k[nestedKey] || []).forEach(function(row) {
            Object.keys(row).forEach(function(c) { colSet[c] = true; });
        });
    });
    var cols = Object.keys(colSet);
    // kut_azonosito legyen az első oszlop
    if (cols.indexOf('kut_azonosito') !== -1) {
        cols = ['kut_azonosito'].concat(cols.filter(function(c) { return c !== 'kut_azonosito'; }));
    }
    var rows = [];
    data.forEach(function(k) {
        (k[nestedKey] || []).forEach(function(r) {
            var obj = { kut_azonosito: k.kut_azonosito };
            cols.forEach(function(c) {
                if (c !== 'kut_azonosito') obj[c] = (r[c] === null || r[c] === undefined) ? '' : r[c];
            });
            rows.push(obj);
        });
    });
    return { rows: rows, cols: cols };
}

// Worksheet oszlopszélesség beállítása
function autoColWidth(ws, rows, cols) {
    var widths = cols.map(function(c) {
        var max = c.length;
        rows.forEach(function(r) { var v = String(r[c] || ''); if (v.length > max) max = v.length; });
        return { wch: Math.min(max + 2, 50) };
    });
    ws['!cols'] = widths;
    return ws;
}

document.getElementById('exportCsvBtn').addEventListener('click', function() {
    var data = getSelectedData();
    var fields = getAlapadatFields();
    var rows = data.map(function(k) {
        return fields.map(function(f) {
            return '"' + String(k[f] === null || k[f] === undefined ? '' : k[f]).replace(/"/g, '""') + '"';
        }).join(';');
    });
    var csv = '\uFEFF' + fields.join(';') + '\n' + rows.join('\n');
    var a = document.createElement('a');
    var dateStr = getDateString();
    a.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8;'}));
    a.download = 'kutak_export_' + dateStr + '.csv';
    a.click();
});

document.getElementById('exportXlsxBtn').addEventListener('click', function() {
    if (typeof XLSX === 'undefined') { alert('SheetJS nem toltodott be. Hasznaljon CSV exportot.'); return; }
    var data = getSelectedData();
    var wb = XLSX.utils.book_new();

    // --- 1. füll: Alapadatok (összes kutak_raw mező) ---
    var alapFields = getAlapadatFields();
    var alapRows = data.map(function(k) {
        var row = {};
        alapFields.forEach(function(f) { row[f] = (k[f] === null || k[f] === undefined) ? '' : k[f]; });
        return row;
    });
    var wsAlap = XLSX.utils.json_to_sheet(alapRows, { header: alapFields });
    autoColWidth(wsAlap, alapRows, alapFields);
    XLSX.utils.book_append_sheet(wb, wsAlap, 'Alapadatok');

    // --- 2. füll: Víztermelés (minden meglévő oszlop dinamikusan) ---
    var vizResult = buildFlatRows(data, 'viztermeles');
    if (vizResult.rows.length) {
        var wsViz = XLSX.utils.json_to_sheet(vizResult.rows, { header: vizResult.cols });
        autoColWidth(wsViz, vizResult.rows, vizResult.cols);
        XLSX.utils.book_append_sheet(wb, wsViz, 'Viztermeles');
    }

    // --- 3. füll: Csövezés ---
    var csovResult = buildFlatRows(data, 'csovezes');
    if (csovResult.rows.length) {
        var wsCsov = XLSX.utils.json_to_sheet(csovResult.rows, { header: csovResult.cols });
        autoColWidth(wsCsov, csovResult.rows, csovResult.cols);
        XLSX.utils.book_append_sheet(wb, wsCsov, 'Csovezes');
    }

    // --- 4. füll: Szűrőzés ---
    var szuroResult = buildFlatRows(data, 'szurozes');
    if (szuroResult.rows.length) {
        var wsSzuro = XLSX.utils.json_to_sheet(szuroResult.rows, { header: szuroResult.cols });
        autoColWidth(wsSzuro, szuroResult.rows, szuroResult.cols);
        XLSX.utils.book_append_sheet(wb, wsSzuro, 'Szurozes');
    }

    // --- 5. füll: Kémiai adatok ---
    var kemiaResult = buildFlatRows(data, 'kemia');
    if (kemiaResult.rows.length) {
        var wsKemia = XLSX.utils.json_to_sheet(kemiaResult.rows, { header: kemiaResult.cols });
        autoColWidth(wsKemia, kemiaResult.rows, kemiaResult.cols);
        XLSX.utils.book_append_sheet(wb, wsKemia, 'Kemia');
    }

    var dateStr = getDateString();
    XLSX.writeFile(wb, 'kutak_export_' + dateStr + '.xlsx');
});

// --- Részletes adattábla ---
function buildDetailTable(kutId) {
    try {
        var kut = null;
        for (var i = 0; i < adatok.length; i++) { if (adatok[i].kut_azonosito === kutId) { kut = adatok[i]; break; } }
        if (!kut) return;
        var detailView = document.getElementById('detailView');
        var tbl = document.getElementById('detailTable');
        detailView.querySelectorAll('h3,h4,table.subtable').forEach(function(el) { el.remove(); });
        tbl.innerHTML = '';
        var skipKeys = ['csovezes','szurozes','viztermeles','kemia','eov_x_clean','eov_y_clean'];
        Object.keys(kut).forEach(function(key) {
            if (skipKeys.indexOf(key) !== -1) return;
            var tr = document.createElement('tr'), th = document.createElement('th'), td = document.createElement('td');
            th.textContent = key;
            td.textContent = (kut[key] === null || kut[key] === undefined) ? '' : kut[key];
            tr.appendChild(th); tr.appendChild(td); tbl.appendChild(tr);
        });
        if (kut.csovezes && kut.csovezes.length) {
            addSubTable(detailView, 'Csovezés', ['Atmero (mm)', 'Melyseg tol (m)', 'Melyseg ig (m)'],
                kut.csovezes.map(function(r) { return [r.atmero_mm, r.melyseg_tol_m, r.melyseg_ig_m]; }));
        }
        if (kut.szurozes && kut.szurozes.length) {
            addSubTable(detailView, 'Szurőzés', ['Atmero (mm)', 'Melyseg tol (m)', 'Melyseg ig (m)'],
                kut.szurozes.map(function(r) { return [r.atmero_mm, r.melyseg_tol_m, r.melyseg_ig_m]; }));
        }
        if (kut.viztermeles && kut.viztermeles.length) {
            addSubTable(detailView, 'Viztermelés', ['Vizhozam (l/p)', 'Vizszint (m)'],
                kut.viztermeles.map(function(r) {
                    var v = r.vizszint_m || '';
                    if (v) v = (v.charAt(0) === '-' ? '' : '+') + v;
                    return [r.vizhozam_l_p || '', v];
                }));
        }
        if (kut.kemia && kut.kemia.length) {
            var h3k = document.createElement('h3'); h3k.textContent = 'Kémiai adatok'; detailView.appendChild(h3k);
            kut.kemia.forEach(function(row, idx) {
                if (kut.kemia.length > 1) {
                    var sub = document.createElement('h4'); sub.textContent = 'Meres ' + (idx + 1); sub.style.marginTop = '10px'; detailView.appendChild(sub);
                }
                var kt = document.createElement('table'); kt.className = 'subtable';
                kt.innerHTML = '<thead><tr><th>Parameter</th><th>Ertek</th></tr></thead><tbody></tbody>';
                detailView.appendChild(kt);
                var tbody = kt.querySelector('tbody');
                Object.keys(row).forEach(function(param) {
                    if (param === 'kut_azonosito') return;
                    var val = row[param];
                    if (val === undefined || val === null || String(val).trim() === '') return;
                    var r2 = document.createElement('tr');
                    r2.innerHTML = '<td>' + param + '</td><td>' + val + '</td>';
                    tbody.appendChild(r2);
                });
            });
        }
    } catch(e) { console.error('buildDetailTable hiba:', kutId, e); }
}
function addSubTable(container, title, headers, rows) {
    var h3 = document.createElement('h3'); h3.textContent = title; container.appendChild(h3);
    var t = document.createElement('table'); t.className = 'subtable';
    t.innerHTML = '<thead><tr>' + headers.map(function(h) { return '<th>' + h + '</th>'; }).join('') + '</tr></thead><tbody></tbody>';
    container.appendChild(t);
    var tbody = t.querySelector('tbody');
    rows.forEach(function(cols) {
        var r = document.createElement('tr');
        r.innerHTML = cols.map(function(c) { return '<td>' + (c || '') + '</td>'; }).join('');
        tbody.appendChild(r);
    });
}

loadFromUrl();
"""

try:
    # Az adatokat beillesztjük a JS kódba (nem f-string, nincs escape probléma)
    print("HTML sablon osszeszerkesztese...")
    JS_CODE_FINAL = JS_CODE.replace('__ADATOK_PLACEHOLDER__', kutak_json_safe)

    html = """<!DOCTYPE html>
<html lang="hu">
<head>
<meta charset="UTF-8">
<title>Hevizk\u00fat Kataszter \u2013 T\u00e9rk\u00e9p + Panel</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
<link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css" />
<style>
* { box-sizing: border-box; }
body { margin: 0; padding: 0; font-family: Arial, sans-serif; }
#map { height: 100vh; width: 100%; }
#topBar {
    position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
    z-index: 10000; background: rgba(255,255,255,0.97);
    padding: 8px 12px; border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25);
    display: flex; gap: 8px; align-items: center; min-width: 480px; flex-wrap: wrap;
}
#searchWrapper { position: relative; flex: 1; min-width: 220px; }
#searchInput { width: 100%; padding: 7px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }
#autocompleteList {
    position: absolute; top: 100%; left: 0; right: 0;
    background: white; border: 1px solid #ccc; border-top: none;
    border-radius: 0 0 4px 4px; z-index: 10001;
    max-height: 220px; overflow-y: auto; display: none;
    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
}
#autocompleteList div { padding: 6px 10px; cursor: pointer; font-size: 13px; }
#autocompleteList div:hover { background: #e8f0fe; }
#searchBtn { padding: 7px 12px; background: #1976d2; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
#searchBtn:hover { background: #1565c0; }
#filterToggleBtn { padding: 7px 10px; background: #f5f5f5; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; font-size: 13px; }
#filterToggleBtn:hover { background: #e0e0e0; }
#searchInfo { font-size: 13px; color: #555; white-space: nowrap; }
#filterPanel {
    position: fixed; top: 62px; left: 50%; transform: translateX(-50%);
    z-index: 9998; background: white; border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    padding: 12px 16px; display: none; gap: 12px;
    flex-wrap: wrap; align-items: flex-end; min-width: 480px;
}
#filterPanel label { font-size: 13px; color: #333; display: block; margin-bottom: 2px; }
#filterPanel input[type=number], #filterPanel select { padding: 5px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; width: 100%; }
.filter-group { display: flex; flex-direction: column; min-width: 110px; }
.filter-check { flex-direction: row !important; align-items: center; gap: 6px; }
.filter-check input { width: auto !important; }
#clearFiltersBtn { padding: 6px 10px; background: #ef5350; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
#sidePanel {
    position: fixed; top: 0; right: -540px; width: 540px; height: 100%;
    background: white; box-shadow: -2px 0 8px rgba(0,0,0,0.2);
    transition: right 0.3s ease; overflow-y: auto;
    padding: 16px 20px 120px; z-index: 9999;
}
#sidePanel.open { right: 0; }
#closePanel { cursor: pointer; font-size: 17px; margin-bottom: 8px; margin-top: 56px; color: #555; user-select: none; }
#closePanel:hover { color: #000; }
#exportBar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
#exportBar button { padding: 5px 10px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
#exportCsvBtn { background: #43a047; color: white; }
#exportXlsxBtn { background: #1565c0; color: white; }
#exportCsvBtn:hover { background: #388e3c; }
#exportXlsxBtn:hover { background: #0d47a1; }
#selectAllBtn { background: #f5f5f5; border: 1px solid #ccc !important; color: #333; }
#detailTable { width: 100%; border-collapse: collapse; }
#detailTable th, #detailTable td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }
#detailTable th { background: #f5f5f5; width: 40%; }
.highlight-row { background-color: #fff9c4 !important; }
#kutTable td, #kutTable th { font-size: 13px; }
table.subtable { width: 100%; border-collapse: collapse; margin-top: 6px; }
table.subtable th, table.subtable td { border: 1px solid #ddd; padding: 5px 7px; font-size: 13px; }
table.subtable thead th { background: #f5f5f5; }
</style>
</head>
<body>
<div id="map"></div>
<div id="topBar">
    <div id="searchWrapper">
        <input id="searchInput" placeholder="Kereses: azonosito, megnevezes, kataszteri szam, VIFIR, telepules..." autocomplete="off" />
        <div id="autocompleteList"></div>
    </div>
    <button id="searchBtn">Kereses</button>
    <button id="filterToggleBtn">Szurok</button>
    <div id="searchInfo"></div>
</div>
<div id="filterPanel">
    <div class="filter-group">
        <label>Telepules</label>
        <select id="filterTelepules"><option value="">- Osszes -</option></select>
    </div>
    <div class="filter-group">
        <label>Epites eve (tol)</label>
        <input type="number" id="filterEvTol" placeholder="pl. 1960" min="1800" max="2100" />
    </div>
    <div class="filter-group">
        <label>Epites eve (ig)</label>
        <input type="number" id="filterEvIg" placeholder="pl. 2000" min="1800" max="2100" />
    </div>
    <div class="filter-group filter-check">
        <input type="checkbox" id="filterVanKemia" />
        <label for="filterVanKemia">Van kemia adat</label>
    </div>
    <div class="filter-group filter-check">
        <input type="checkbox" id="filterVanViz" />
        <label for="filterVanViz">Van viztermelés adat</label>
    </div>
    <button id="clearFiltersBtn">Torles</button>
</div>
<div id="sidePanel">
    <div id="closePanel">X Bezaras</div>
    <div id="listView">
        <h2 style="margin:0 0 8px;">Kut talalatok</h2>
        <div id="exportBar">
            <button id="selectAllBtn">Osszes kijelolese</button>
            <button id="exportCsvBtn">CSV export</button>
            <button id="exportXlsxBtn">Excel export</button>
        </div>
        <table id="kutTable" class="display" style="width:100%">
            <thead>
                <tr>
                    <th><input type="checkbox" id="masterCheck" /></th>
                    <th>Kut azonosito</th>
                    <th>Kataszteri szam</th>
                    <th>VIFIR kod</th>
                    <th>Epites eve</th>
                    <th>Reszletek</th>
                </tr>
            </thead>
            <tbody></tbody>
        </table>
    </div>
    <div id="detailView" style="display:none;">
        <button id="backToList">Vissza a listahoz</button>
        <h2>Reszletes adatok</h2>
        <table id="detailTable"></table>
    </div>
</div>
<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
<script src="https://unpkg.com/xlsx/dist/xlsx.full.min.js"></script>
<script>
""" + JS_CODE_FINAL + """
</script>
</body>
</html>"""

    print("HTML fajl irasa...")
    output_filename = Path(__file__).parent / "ujterkep3.html"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(html)

    print("")
    print("=" * 60)
    print("SIKER! A fajl elkeszult:")
    print("  " + str(output_filename))
    print("=" * 60)

except Exception as e:
    print("")
    print("=" * 60)
    print("HIBA TORTENT!")
    print("-" * 60)
    traceback.print_exc()
    print("=" * 60)

finally:
    input("\nNyomj Entert a bezarashoz...")
