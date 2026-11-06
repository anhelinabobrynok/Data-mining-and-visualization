# -*- coding: utf-8 -*-
"""
Резервне джерело для ЛР5: знімок OSM з файлу .osm.pbf замість живого Overpass.

Навіщо: 01.11.2026 головний сервер overpass-api.de відповідав HTTP 502,
дзеркала private.coffee і kumi.systems — таймаутом, osm.jp — помилкою SSL
(див. probe_mirrors.py). Регіональні витяги OSM при цьому доступні:
download.openstreetmap.fr/extracts/europe/ukraine/kharkiv_oblast-latest.osm.pbf

Що робить модуль: з pbf області вирізає прямокутник міста і пише два файли
OSM XML, які osmnx читає своїми ж функціями:
  * features.osm — об'єкти з тегами historic / tourism / railway / amenity
    (разом із вузлами і членами мультиполігонів, щоб збудувати геометрію);
  * walk.osm     — шляхи, що проходять ТОЙ САМИЙ фільтр, яким osmnx
    будує network_type='walk' (скопійовано з osmnx/_overpass.py, v2.1.1).
Далі ox.features_from_xml(..., polygon, tags) і ox.graph_from_xml(...) дають
ті самі таблиці, що й features_from_polygon / graph_from_polygon.
"""
import re, time, os
import osmium

FEATURE_KEYS = ('historic', 'tourism', 'railway', 'building', 'amenity')

# osmnx 2.1.1, filters["walk"] + settings.default_access
WALK_HW_BAD = re.compile(r'abandoned|bus_guideway|construction|cycleway|motor|no|planned|'
                         r'platform|proposed|raceway|razed|rest_area|services')


def walk_ok(t):
    hw = t.get('highway')
    if hw is None:
        return False
    if re.search('yes', t.get('area', '')):
        return False
    if re.search('private', t.get('access', '')):
        return False
    if WALK_HW_BAD.search(hw):
        return False
    if re.search('no', t.get('foot', '')) or re.search('private', t.get('service', '')):
        return False
    for k in ('sidewalk', 'sidewalk:both', 'sidewalk:left', 'sidewalk:right'):
        if re.search('separate', t.get(k, '')):
            return False
    return True


def is_feature(t):
    return any(k in t for k in FEATURE_KEYS) and (
        'historic' in t or 'tourism' in t or
        t.get('railway') in ('station', 'halt') or t.get('building') == 'train_station' or
        t.get('amenity') in ('cafe', 'restaurant', 'drinking_water', 'toilets'))


def build(pbf, bbox, out_dir):
    """bbox = (west, south, east, north). Повертає шляхи до двох .osm і статистику."""
    w, s, e, n = bbox
    inside = lambda lon, lat: w <= lon <= e and s <= lat <= n
    t0 = time.time()

    # 1) мультиполігони-пам'ятки: які шляхи є їхніми членами
    rel_members, rel_keep = {}, set()
    for r in osmium.FileProcessor(pbf, osmium.osm.RELATION):
        tags = dict(r.tags)
        if tags.get('type') == 'multipolygon' and is_feature(tags):
            rel_members[r.id] = [m.ref for m in r.members if m.type == 'w']
    member_ways = {wid for ws in rel_members.values() for wid in ws}

    # 2) шляхи з координатами вузлів: відбір за фільтром і прямокутником
    walk_ways, feat_ways, walk_nodes, feat_nodes = set(), set(), set(), set()
    for way in osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations():
        if not way.is_way():
            continue
        tags = dict(way.tags)
        wk, ft, mb = walk_ok(tags), is_feature(tags), way.id in member_ways
        if not (wk or ft or mb):
            continue
        try:
            if not any(inside(nd.lon, nd.lat) for nd in way.nodes):
                continue
        except osmium.InvalidLocationError:
            continue
        refs = [nd.ref for nd in way.nodes]
        if wk:
            walk_ways.add(way.id); walk_nodes.update(refs)
        if ft or mb:
            feat_ways.add(way.id); feat_nodes.update(refs)
    rel_keep = {rid for rid, ws in rel_members.items() if any(x in feat_ways for x in ws)}

    # 3) запис двох XML (порядок: вузли, шляхи, відношення)
    paths = {k: os.path.join(out_dir, k + '.osm') for k in ('features', 'walk')}
    for p in paths.values():
        if os.path.exists(p):
            os.remove(p)
    wf, ww = osmium.SimpleWriter(paths['features']), osmium.SimpleWriter(paths['walk'])
    n_feat_nodes = 0
    for o in osmium.FileProcessor(pbf):
        if o.is_node():
            if o.id in walk_nodes:
                ww.add_node(o)
            tagged = is_feature(dict(o.tags)) and o.location.valid() and inside(o.lon, o.lat)
            if o.id in feat_nodes or tagged:
                wf.add_node(o); n_feat_nodes += tagged
        elif o.is_way():
            if o.id in walk_ways:
                ww.add_way(o)
            if o.id in feat_ways:
                wf.add_way(o)
        elif o.is_relation() and o.id in rel_keep:
            wf.add_relation(o)
    wf.close(); ww.close()

    stats = {'шляхів_walk': len(walk_ways), 'вузлів_walk': len(walk_nodes),
             'шляхів_об’єктів': len(feat_ways), 'вузлів_об’єктів': n_feat_nodes,
             'мультиполігонів': len(rel_keep), 'секунд': round(time.time() - t0, 1),
             'features_МБ': round(os.path.getsize(paths['features']) / 1e6, 2),
             'walk_МБ': round(os.path.getsize(paths['walk']) / 1e6, 2)}
    return paths, stats


def walk_graph(walk_xml, poly):
    """Відтворює ox.graph_from_polygon(poly, network_type='walk') з локального файлу."""
    import osmnx as ox
    G = ox.graph_from_xml(walk_xml, bidirectional=True, simplify=False, retain_all=True)
    G = ox.truncate.truncate_graph_polygon(G, poly, truncate_by_edge=False)
    G = ox.simplification.simplify_graph(G)
    G = ox.truncate.largest_component(G, strongly=False)
    return G
