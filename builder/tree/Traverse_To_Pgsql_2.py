# FEV, 5 2016
# WE REMOVE THE WRITING TO JSON AND trees. This is performed by another code.
# This code is more complete than the previous one.
# I switched to ete3
# We read the tree from external file (trees are retrieved with the code called "gettrees.py").
# Added possibility to have groups containing only one descendants to be visible. Adds a few zoom levels (not so many)

import json
import logging
import math
import os
from typing import Literal

import numpy as np

# import cPickle as pickle
from config import BUILD_DIRECTORY, TAXO_DIRECTORY
from db import db_connection
from ete3 import Tree
from tqdm import tqdm
from utils import download_file_if_newer

# print args

logger = logging.getLogger("LifemapBuilder")


##update db (if requested?)
def updateDB():
    logger.info("Updating databases...")
    downloaded = download_file_if_newer(
        host="ftp.ncbi.nlm.nih.gov",
        remote_file="/pub/taxonomy/taxdump.tar.gz",
        local_file=TAXO_DIRECTORY / "taxdump.tar.gz",
    )
    if downloaded:
        os.system(f"tar xvzf {TAXO_DIRECTORY / 'taxdump.tar.gz'} -C {TAXO_DIRECTORY}")


def simplify_tree(arbre):
    initialSize = len(arbre)
    for n in arbre.traverse():
        if n.is_leaf() and (n.rank_en == "no rank"):
            n.detach()
        else:
            if (
                ("Unclassified" in n.sci_name)
                or ("unclassified" in n.sci_name)
                or ("uncultured" in n.sci_name)
                or ("Uncultured" in n.sci_name)
                or ("unidentified" in n.sci_name)
                or ("Unidentified" in n.sci_name)
                or ("environmental" in n.sci_name)
                or ("sp." in n.sci_name)
            ):
                n.detach()
    logger.info("Tree HAS BEEN simplified")
    finalSize = len(arbre)
    diffInSize = initialSize - finalSize
    logger.info(
        str(diffInSize)
        + " tips have been removed ("
        + str(round(float(diffInSize) / float(initialSize) * 100, 2))
        + "%)"
    )
    logger.info("FINAL TREE SIZE: " + str(finalSize))
    return arbre


def midpoint(x1, y1, x2, y2):
    # Input values as degrees
    # Convert to radians
    lat1 = math.radians(x1)
    lon1 = math.radians(y1)
    lat2 = math.radians(x2)
    lon2 = math.radians(y2)
    cos1 = math.cos(lat1)
    cos2 = math.cos(lat2)
    bx = cos2 * math.cos(lon2 - lon1)
    by = cos2 * math.sin(lon2 - lon1)
    lat3 = math.atan2(
        math.sin(lat1) + math.sin(lat2),
        math.sqrt((cos1 + bx) * (cos1 + bx) + by**2),
    )
    lon3 = lon1 + math.atan2(by, cos1 + bx)
    return [math.degrees(lat3), math.degrees(lon3)]


def rad(deg):
    return (deg * np.pi) / 180


def halfCircle(x, y, r, start, end, nsteps):
    rs = np.linspace(start, end, num=nsteps)
    xc = x + r * np.cos(rs)
    yc = y + r * np.sin(rs)
    return (xc, yc)


def ellipse(x, y, r, alpha, nsteps):
    start = 0
    end = np.pi + start
    rs = np.linspace(start, end, num=nsteps)
    a = r
    b = (
        float(r) / 6
    )  ##Change this value to change the shape of polygons. This controls how flat is the elliptic side of the polygon. The other side is always a half cricle.
    xs = a * np.cos(rs)
    ys = b * np.sin(rs)
    ##rotation
    cosa = np.cos(alpha)
    sina = np.sin(alpha)
    xs2 = x + (xs * cosa - ys * sina)
    ys2 = y + (xs * sina + ys * cosa)
    return (xs2, ys2)


def HalfCircPlusEllips(x, y, r, alpha, start, end, nsteps):
    circ = halfCircle(x, y, r, start, end, nsteps)
    elli = ellipse(x, y, r, alpha, nsteps)
    return (np.concatenate((circ[0], elli[0])), np.concatenate((circ[1], elli[1])))


def get_way_record(node, id, cur, groupnb):
    # Create branch names
    Upsci_name = node.up.sci_name
    Upcommon_name_en = node.up.common_name_en
    Downsci_name = node.sci_name
    Downcommon_name_en = node.common_name_en
    left = Upsci_name + " " + Upcommon_name_en
    right = Downsci_name + " " + Downcommon_name_en
    if node.x >= node.up.x:  # we are on the right
        wayName = "\\u2190  " + left + "     -     " + right + "  \\u2192"
    else:  # we are on the left
        wayName = "\\u2190  " + right + "     -     " + left + "  \\u2192"

    ##new with midpoints:
    midlatlon = midpoint(node.up.x, node.up.y, node.x, node.y)

    record = (
        id,
        "TRUE",
        int(node.zoomview),
        groupnb,
        wayName,
        f"LINESTRING({node.up.x:.20f} {node.up.y:.20f}, {midlatlon[0]:.20f} {midlatlon[1]:.20f}, {node.x:.20f} {node.y:.20f} )",
    )

    return record


def get_polyg_record(node, ids, groupnb):
    polyg = HalfCircPlusEllips(
        node.x,
        node.y,
        node.ray,
        rad(node.alpha) + np.pi / 2,
        rad(node.alpha) - np.pi / 2,
        rad(node.alpha) + np.pi / 2,
        30,
    )
    polygcenter = (np.mean(polyg[0]), np.mean(polyg[1]))
    cooPolyg = "POLYGON((%.20f %.20f " % (polyg[0][0], polyg[1][0])
    for i in range(1, 59):
        cooPolyg += ",%.20f %.20f" % (polyg[0][i], polyg[1][i])
    cooPolyg += ",%.20f %.20f" % (polyg[0][0], polyg[1][0])
    # to close the ring...
    cooPolyg += "))"
    polygon_record = (
        int(ids[60]),
        groupnb,
        True,
        node.taxid,
        node.sci_name,
        node.common_name_en,
        node.common_name_fr,
        node.rank_en,
        node.rank_fr,
        int(node.nbdesc),
        int(node.zoomview),
        cooPolyg,
    )

    point_record = (
        int(ids[61]),
        True,
        node.taxid,
        node.sci_name,
        node.common_name_en,
        node.common_name_fr,
        node.rank_en,
        node.rank_fr,
        int(node.nbdesc),
        int(node.zoomview),
        f"POINT({polygcenter[0]:.20f} {polygcenter[1]:.20f})",
    )

    # we add a way on which we will write the rank
    cooLine = "LINESTRING(%.20f %.20f" % (polyg[0][35], polyg[1][35])
    for i in range(36, 45):
        cooLine += ",%.20f %.20f" % (polyg[0][i], polyg[1][i])
    cooLine += ")"

    line_record = (
        int(ids[62]),
        groupnb,
        True,
        node.sci_name,
        int(node.zoomview),
        node.rank_en,
        node.rank_fr,
        int(node.nbdesc),
        cooLine,
    )

    return polygon_record, point_record, line_record


def node2json(node) -> str:
    sci_name = node.sci_name
    sci_name = sci_name.replace('"', '\\"')
    common_name_en = node.common_name_long_en
    common_name_en = common_name_en.replace('"', '\\"')
    common_name_fr = node.common_name_long_fr
    common_name_fr = common_name_fr.replace('"', '\\"')
    ##new attributes
    authority = node.authority
    authority = authority.replace('"', '\\"')
    synonym = node.synonym
    synonym = synonym.replace('"', '\\"')
    out = f"""{{
        "taxid": "{node.taxid}",
        "sci_name": "{sci_name}",
        "common_name_en": "{common_name_en}",
        "common_name_fr": "{common_name_fr}",
        "authority": "{authority}",
        "synonym": "{synonym}",
        "rank_en": "{node.rank_en}",
        "rank_fr": "{node.rank_fr}",
        "all": "{sci_name} | {common_name_en} | {node.rank_en} | {node.taxid}",
        "zoom": {int(node.zoomview + 4)},
        "nbdesc": {node.nbdesc},
        "coordinates": [{node.y:.20f}, {node.x:.20f}],
        "lat": {node.y:.20f},
        "lon": {node.x:.20f}
    }}"""
    return out


def traverse_tree(
    tree: Tree,
    groupnb: Literal["1", "2", "3"],
    starti: int,
) -> int:
    """
    Open taxonomic tree and recode it into PostGRES/PostGIS database for visualisation in Lifemap.

    Parameters
    ----------
    tree : ete3.Tree
        Global NCBI tree
    groupnb : {'1', '2', '3'}
        Group to look at. Can be 1,2 or 3 for Archaea, Eukaryotes and Bacteria respectively
    starti : int
        index of the first node met in the tree
    updatedb : bool, optional
        Should the NCBI taxonomy db be updated ?, by default True

    Returns
    -------
    int
        ndid
    """

    ##let's try to write the tree entirely here, in a file

    logger.info("Downloading tree...")

    if groupnb == "1":
        t = tree["2157"].copy()
        logger.info("Archaeal tree loaded...")
        t.write(
            outfile=BUILD_DIRECTORY / "ARCHAEA",
            features=["name", "taxid"],
            format_root_node=True,
        )
        t.x = 6.0
        t.y = 9.660254 - 10.0
        t.alpha = 30.0
        t.ray = 10.0
    if groupnb == "2":
        t = tree["2759"].copy()
        logger.info("Eukaryotic tree loaded")
        t.write(
            outfile=BUILD_DIRECTORY / "EUKARYOTES",
            features=["name", "taxid"],
            format_root_node=True,
        )
        t.x = -6.0
        t.y = 9.660254 - 10.0
        t.alpha = 150.0
        t.ray = 10.0
    if groupnb == "3":
        t = tree["2"].copy()
        logger.info("Bacterial tree loaded")
        t.write(
            outfile=BUILD_DIRECTORY / "BACTERIA",
            features=["name", "taxid"],
            format_root_node=True,
        )
        t.x = 0.0
        t.y = -11.0
        t.alpha = 270.0
        t.ray = 10.0

    t.zoomview = np.ceil(np.log2(30 / t.ray))

    # specis and node ids
    nbsp = len(t)
    spid = starti
    ndid = starti + nbsp
    maxZoomView = 0

    logger.info("Tree traversal...")
    points_records = []
    for n in tqdm(t.traverse(), total=len(t)):
        special = 0
        n.dist = 1.0
        tot = 0.0
        if n.is_leaf():
            spid = spid + 1
            n.id = spid
        else:
            ndid = ndid + 1
            n.id = ndid
        child = n.children
        ##NEW  -->|
        if (len(child) == 1) & (len(n) > 1):
            special = 1
        if (len(child) == 1) & (len(n) == 1):
            special = 2
        ## |<-- NEW
        for i in child:
            tot = tot + np.sqrt(len(i))
        nbdesc = len(n)
        n.nbdesc = nbdesc

        angles = []
        ray = n.ray
        for i in child:
            # i.ang = 180*(len(i)/float(nbdesc))/2;
            i.ang = 180 * (np.sqrt(len(i)) / tot) / 2
            # using sqrt we decrease difference between large and small groups
            angles.append(i.ang)
            if special == 1:
                i.ray = ray - (ray * 20) / 100
            else:
                if special == 2:
                    i.ray = ray - (ray * 50) / 100
                else:
                    i.ray = (ray * np.sin(rad(i.ang)) / np.cos(rad(i.ang))) / (
                        1 + (np.sin(rad(i.ang)) / np.cos(rad(i.ang)))
                    )
            i.dist = ray - i.ray
        ang = np.repeat(angles, 2)
        ang = np.cumsum(ang)
        ang = ang[0::2]
        ang = [i - (90 - n.alpha) for i in ang]
        cpt = 0
        for i in child:
            i.alpha = ang[cpt]
            i.x = n.x + i.dist * np.cos(rad(i.alpha))
            i.y = n.y + i.dist * np.sin(rad(i.alpha))
            i.zoomview = np.ceil(np.log2(30 / i.ray))
            if i.zoomview <= 0:
                i.zoomview = 0
            if maxZoomView < i.zoomview:
                maxZoomView = i.zoomview
            cpt = cpt + 1
        # Append node info to postgis COPY records
        points_records.append(
            (
                n.id,
                n.taxid,
                n.sci_name,
                n.common_name_en,
                n.common_name_fr,
                n.rank_en,
                n.rank_fr,
                n.nbdesc,
                int(n.zoomview),
                n.is_leaf(),
                f"POINT({n.x:.20f} {n.y:.20f})",
            )
        )

    # Postgis connection
    conn = db_connection()
    cur = conn.cursor()

    logger.info("Inserting data into postgis")
    with cur.copy(
        "COPY points (id, taxid, sci_name, common_name_en, common_name_fr, rank_en, rank_fr, nbdesc, zoomview, tip,geom_txt) FROM STDIN"
    ) as copy:
        for record in tqdm(points_records):
            copy.write_row(record)
    conn.commit()

    logger.info("Tree traversal 2... ")

    lines_records = []
    polygons_records = []
    polygons_points_records = []
    polygons_lines_records = []

    ##LAST LOOP TO write coords of polygs and JSON file
    json_file = open(BUILD_DIRECTORY / f"TreeFeatures{groupnb}.json", "w")
    first = True
    for n in tqdm(t.traverse(), total=len(t)):
        if first:
            json_file.write("[")
            first = False
        else:
            json_file.write(",")
        if not n.is_root():
            ndid = ndid + 1
            lines_records.append(get_way_record(n, ndid, cur, groupnb))
        if not n.is_leaf():
            indexes = np.linspace(ndid + 1, ndid + 63, num=63)
            polygon_record, point_record, line_record = get_polyg_record(
                n, indexes, groupnb
            )
            polygons_records.append(polygon_record)
            polygons_points_records.append(point_record)
            polygons_lines_records.append(line_record)
            ndid = ndid + 63
        json_file.write(node2json(n))

    json_file.write("]")
    json_file.close()

    logger.info("Inserting lines data into postgis")
    with cur.copy(
        "COPY lines (id, branch, zoomview, ref, name, geom_txt) FROM STDIN"
    ) as copy:
        for record in tqdm(lines_records):
            copy.write_row(record)
    conn.commit()

    logger.info("Inserting polygons data into postgis")
    with cur.copy(
        "COPY polygons (id, ref, clade, taxid, sci_name, common_name_en, common_name_fr, rank_en, rank_fr,nbdesc,zoomview, geom_txt) FROM STDIN"
    ) as copy:
        for record in tqdm(polygons_records):
            copy.write_row(record)
    conn.commit()

    logger.info("Inserting polygons points data into postgis")
    with cur.copy(
        "COPY points (id, cladecenter, taxid, sci_name, common_name_en, common_name_fr,rank_en, rank_fr,nbdesc,zoomview, geom_txt) FROM STDIN"
    ) as copy:
        for record in tqdm(polygons_points_records):
            copy.write_row(record)
    conn.commit()

    logger.info("Inserting polygons lines data into postgis")
    with cur.copy(
        "COPY lines (id, ref, rankname, sci_name, zoomview, rank_en, rank_fr, nbdesc, geom_txt) FROM STDIN"
    ) as copy:
        for record in tqdm(polygons_lines_records):
            copy.write_row(record)
    conn.commit()

    ##we add the way from LUCA to the root of the subtree
    ndid = ndid + 1
    command = (
        "INSERT INTO lines (id, branch, zoomview, ref, way) VALUES(%d,'TRUE', '4','%s',ST_Transform(ST_GeomFromText('LINESTRING(0 -4.226497, %.20f %.20f)', 4326), 3857));"
        % (ndid, groupnb, t.x, t.y)
    )
    cur.execute(command)
    conn.commit()

    logger.info(f"DONE - ndid:{ndid} - spid:{spid} - Max zoom view: {maxZoomView}")

    conn.close()
    return ndid