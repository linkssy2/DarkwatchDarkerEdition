"""Adapt the disc's actual boss arms to the existing first-person weapon rig.

No mesh or texture payload is distributed. The original bare hands, both UV
sets and skin material are retained; native finger branches receive smooth
weights for the player's articulated grip. No weapon animation is changed.
"""
from collections import Counter
import hashlib
import math
import struct

import character_boss as boss
import character_repaint as rw


SOURCE_SHA = 'cab37ad6d148fbef05bd859b91d51c0d8b905a7f9e918703c54aed35ceedd0ea'


def _point(p, matrix):
    return tuple(sum(p[i]*matrix[i*4+j] for i in range(3))+matrix[12+j] for j in range(3))


def _inverse(matrix):
    out = [0.] * 16
    a,b,c,d,e,f,g,h,i = (matrix[k] for k in (0,1,2,4,5,6,8,9,10))
    cofactors = (e*i-f*h,c*h-b*i,b*f-c*e,f*g-d*i,a*i-c*g,c*d-a*f,d*h-e*g,b*g-a*h,a*e-b*d)
    determinant = a*cofactors[0]+b*cofactors[3]+c*cofactors[6]
    if abs(determinant) < 1e-10:
        raise ValueError('Singular arm bind matrix')
    for i in range(3):
        for j in range(3):
            out[i*4+j] = cofactors[i*3+j]/determinant
    out[15] = 1.
    out[12:15] = [-sum(matrix[12+j]*out[j*4+i] for j in range(3)) for i in range(3)]
    return out


def _geometry(raw, index):
    geos = [(a,z) for t,a,z,p in boss._records(raw) if t == 15]
    if not 0 <= index < len(geos):
        raise ValueError('Missing hand source geometry')
    records = list(boss._records(raw, *geos[index], 15))
    a,z = next((a,z) for t,a,z,p in records if t == 0x510)
    chunks = rw.chunks(raw[a:z])
    if len(chunks) != 1 or chunks[0][0] != 1:
        raise ValueError('Unexpected hand native buffer')
    start = a+12
    platform,size = struct.unpack_from('<II',raw,start)
    header = start+4
    _,count,primitive,vertices,stride = struct.unpack_from('<HHIII',raw,header+4)
    vb = header+size
    if platform != 5 or stride not in (28,36) or primitive not in (5,6) or vb+vertices*stride != z:
        raise ValueError('Unexpected hand vertex schema')
    positions = [struct.unpack_from('<3f',raw,vb+i*stride) for i in range(vertices)]
    uv = [struct.unpack_from('<2f',raw,vb+i*stride+20) for i in range(vertices)]
    uv1 = [struct.unpack_from('<2f',raw,vb+i*stride+28) for i in range(vertices)] if stride == 36 else []
    colors = [struct.unpack_from('<I',raw,vb+i*stride+16)[0] for i in range(vertices)]
    triangles = []
    for i in range(count):
        _,_,n,offset,_,_ = struct.unpack_from('<6I',raw,header+36+i*24)
        at = header-24+offset
        if not header+36+count*24 <= at or at+2*n > vb:
            raise ValueError('Invalid hand index range')
        indices = struct.unpack_from('<'+str(n)+'H',raw,at)
        if any(v >= vertices for v in indices):
            raise ValueError('Hand vertex index out of bounds')
        if primitive == 5:
            if n % 3:
                raise ValueError('Incomplete hand triangle')
            triangles.extend(tuple(indices[j:j+3]) for j in range(0,n,3))
        else:
            for j in range(n-2):
                tri = tuple(indices[j:j+3])
                if len(set(tri)) == 3:
                    triangles.append(tri if j%2 == 0 else (tri[1],tri[0],tri[2]))
    a,z = next((a,z) for t,a,z,p in records if t == 0x116)
    start = a+12
    platform,bones = struct.unpack_from('<II',raw,start)
    palette = struct.unpack_from('<256i',raw,start+8)
    _,influences,_,skin_stride = struct.unpack_from('<4I',raw,start+2056)
    if platform != 5 or bones not in (22,51) or not 1 <= influences <= 4 or skin_stride != influences*3:
        raise ValueError('Unexpected hand skin schema')
    at = start+2072
    weights = []
    for i in range(vertices):
        values = raw[at+i*skin_stride:at+i*skin_stride+influences]
        indices = struct.unpack_from('<'+str(influences)+'H',raw,at+i*skin_stride+influences)
        if sum(values) != 255 or any(v%3 or v//3 >= 256 for v in indices):
            raise ValueError('Invalid hand skin weights')
        weight = {palette[v//3]: w/255 for v,w in zip(indices,values) if w}
        if any(not 0 <= b < bones for b in weight):
            raise ValueError('Invalid hand bone')
        weights.append(weight)
    inv = at+vertices*skin_stride
    if inv+bones*64+12 != z:
        raise ValueError('Unexpected hand inverse binds')
    matrices = [struct.unpack_from('<16f',raw,inv+i*64) for i in range(bones)]
    if any(not math.isfinite(v) for row in positions+uv+matrices for v in row):
        raise ValueError('Nonfinite hand geometry')
    return dict(positions=positions, uv=uv, uv1=uv1, colors=colors, triangles=triangles,
                weights=weights, inverse=matrices, skin_prefix=raw[start:start+2072],
                inverse_bytes=raw[inv:inv+bones*64], geometry=raw[geos[index][0]-12:geos[index][1]])


def _finger_weights(source, used, triangles, inverses, old, new, child, side, scale, target, binds):
    """Diffuse anatomical finger seeds across the connected original surface.

    The boss has rigid hand bones. Nearest-surface transfer from a gloved hand
    crosses adjacent fingers, so seed each native finger branch independently.
    Harmonic interpolation joins these seeds smoothly through the palm.
    """
    points, weld, nodes = [], {}, []
    for vertex in used:
        point = _point(tuple(v*boss.SCALE for v in source['positions'][vertex]), inverses[old[2]])
        key = tuple(round(v,6) for v in point)
        if key not in weld:
            weld[key] = len(points)
            points.append(point)
        nodes.append(weld[key])
    lookup = dict(zip(used,nodes))
    adjacency = [{} for _ in points]
    for triangle in triangles:
        for a,b in zip(triangle,(*triangle[1:],triangle[0])):
            a,b = lookup[a],lookup[b]
            if a != b:
                adjacency[a][b] = adjacency[b][a] = 1/max(math.dist(points[a],points[b]),1e-6)
    reach = max(p[0] for p in points)
    def branches(cut):
        pending = {i for i,p in enumerate(points) if p[0] > cut}
        result = []
        while pending:
            stack, found = [min(pending)], set()
            while stack:
                n = stack.pop()
                if n not in pending:
                    continue
                pending.remove(n)
                found.add(n)
                stack.extend(adjacency[n])
            if len(found) > 2:
                result.append(found)
        return sorted(result,key=lambda group:sum(points[n][1] for n in group)/len(group))
    fingers, thumb = branches(reach*.63), branches(reach*.46)
    if len(fingers) != 5 or len(thumb) != 2:
        raise ValueError('Original hand finger branches differ')
    families = ((7,), (7,), (7,), (5,6), (9,10)) if side == 'left' else (
        (17,18), (17,18), (17,18), (15,16), (19,20))
    fixed = {n:{new[2]:1.} for n,p in enumerate(points) if p[0] < reach*.26}
    for j,(group,bones) in enumerate(zip(fingers,families)):
        if j == 4:
            group = thumb[-1]
        joint = _point(binds[bones[-1]][12:15],target['inverse'][new[2]])[2]/scale
        for n in group:
            f = max(0.,min(1.,(points[n][0]-joint+.009)/.018))
            fixed[n] = {bones[0]:1.} if len(bones) == 1 else {bones[0]:1-f,bones[1]:f}
    bones = sorted({bone for row in fixed.values() for bone in row})
    weights = [[float(b == new[2]) for b in bones] for _ in points]
    for n,row in fixed.items():
        weights[n] = [row.get(b,0.) for b in bones]
    moving = [n for n in range(len(points)) if n not in fixed]
    neighbors = {n:list(adjacency[n].items()) for n in moving}
    totals = {n:sum(v for _,v in neighbors[n]) for n in moving}
    for _ in range(800):
        difference = 0.
        for n in moving:
            row = [sum(weights[k][j]*v for k,v in neighbors[n])/totals[n] for j in range(len(bones))]
            difference = max(difference,max(abs(a-b) for a,b in zip(weights[n],row)))
            weights[n] = row
        if difference < 1e-7:
            break
    output = []
    for vertex,node in zip(used,nodes):
        original = source['weights'][vertex]
        total = sum(original.get(b,0.) for b in (*old,child))
        row = {b:original.get(a,0.)/total for a,b in zip(old[:2],new[:2])}
        hand = (original.get(old[2],0.)+original.get(child,0.))/total
        row.update({b:v*hand for b,v in zip(bones,weights[node])})
        ids = sorted(row,key=lambda b:(-row[b],b))[:4]
        ids += [0]*(4-len(ids))
        values = [row.get(b,0.)/sum(row.get(i,0.) for i in ids)*255 for b in ids]
        quantized = [math.floor(v) for v in values]
        for j in sorted(range(4),key=lambda j:-(values[j]-quantized[j]))[:255-sum(quantized)]:
            quantized[j] += 1
        output.append((ids,quantized))
    return output


def _cap(boundary, mapping, positions, inverse):
    """Triangulate the planar, occasionally concave proximal ring outward."""
    successor = {b:a for a,b in boundary}  # Reverse the original surface edge.
    if len(successor) != len(boundary):
        raise ValueError('Nonmanifold arm cut')
    ring = [min(successor)]
    while successor[ring[-1]] != ring[0]:
        following = successor[ring[-1]]
        if following in ring:
            raise ValueError('Disconnected arm cut')
        ring.append(following)
    if len(ring) != len(boundary):
        raise ValueError('Incomplete arm cut ring')
    points = {i:_point(positions[mapping[i]],inverse)[:2] for i in ring}
    def cross(a,b,c):
        a,b,c = points[a],points[b],points[c]
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    area = sum(points[a][0]*points[b][1]-points[b][0]*points[a][1]
               for a,b in zip(ring,ring[1:]+ring[:1]))
    direction = 1 if area > 0 else -1
    triangles = []
    while len(ring) > 3:
        for j,b in enumerate(ring):
            a,c = ring[j-1],ring[(j+1)%len(ring)]
            if cross(a,b,c)*direction <= 1e-12:
                continue
            if any(min(cross(a,b,p),cross(b,c,p),cross(c,a,p)) >= -1e-12 if direction == 1 else
                   max(cross(a,b,p),cross(b,c,p),cross(c,a,p)) <= 1e-12
                   for p in ring if p not in (a,b,c)):
                continue
            triangles.append((mapping[a],mapping[b],mapping[c]))
            ring.pop(j)
            break
        else:
            raise ValueError('Cannot triangulate original arm cut')
    triangles.append(tuple(mapping[i] for i in ring))
    return triangles


def _boundary(triangles, positions):
    weld = {}
    vertices = {i:weld.setdefault(tuple(round(v,5) for v in positions[i]),i)
                for i in sorted({i for tri in triangles for i in tri})}
    edges = Counter(tuple(sorted((vertices[a],vertices[b]))) for tri in triangles
                    for a,b in zip(tri,(*tri[1:],tri[0])))
    boundary = [(vertices[a],vertices[b]) for tri in triangles for a,b in zip(tri,(*tri[1:],tri[0]))
                if edges[tuple(sorted((vertices[a],vertices[b])))] == 1]
    return vertices,boundary


def _adapt(source, target):
    inverses = [list(m) for m in source['inverse']]
    for matrix in inverses:
        matrix[12:15] = [v*boss.SCALE for v in matrix[12:15]]
    old_binds, binds = list(map(_inverse,inverses)),list(map(_inverse,target['inverse']))
    src = [tuple(v*boss.SCALE for v in p) for p in source['positions']]
    model = {name:[] for name in ('positions','uv','uv1','colors','bones','weights','triangles','source_vertices','sides','metrics','cap_faces')}
    for side,old,new,child,fingers in (
            ('left',(18,19,20),(1,2,4),21,range(5,11)),
            ('right',(13,14,15),(11,12,14),16,range(15,22))):
        allowed = [sum(w.get(b,0.) for b in (*old,child)) >= .98 for w in source['weights']]
        triangles = [tri for tri in source['triangles'] if all(allowed[i] for i in tri)]
        if len(triangles) != 848:
            raise ValueError('Original complete arm topology differs')
        vertices,boundary = _boundary(triangles,source['positions'])
        boundary_ids = {i for edge in boundary for i in edge}
        # One tiny proximal ear per arm lies wholly on the cut ring. Flattening
        # it would overlap the new cap; retriangulate it as part of that cap.
        ears = [tri for tri in triangles if all(vertices[i] in boundary_ids for i in tri)]
        if len(boundary) != 12 or len(ears) != 1:
            raise ValueError('Original proximal arm cut differs')
        triangles = [tri for tri in triangles if tri not in ears]
        used = sorted({i for tri in triangles for i in tri})
        if len(used) < 600:
            raise ValueError('Original complete arm topology differs')
        scales = []
        for j,(a,b) in enumerate(zip(old,new)):
            if j < 2:
                length = math.dist(old_binds[a][12:15],old_binds[old[j+1]][12:15])
                wanted = math.dist(binds[b][12:15],binds[new[j+1]][12:15])
            else:
                length = max(_point(src[i],inverses[a])[0] for i,w in enumerate(source['weights'])
                             if w.get(a,0.)+w.get(child,0.) > .5)
                wanted = max(_point(p,target['inverse'][b])[2] for p,w in zip(target['positions'],target['weights'])
                             if sum(w.get(k,0.) for k in (b,*fingers)) > .5)
            if not .01 < length < 1 or not .01 < wanted < 1:
                raise ValueError('Unexpected arm bind proportions')
            scales.append(wanted/length)
        mapping = {i:len(model['positions'])+j for j,i in enumerate(used)}
        for i in used:
            weights = [source['weights'][i].get(b,0.) for b in old]
            weights[2] += source['weights'][i].get(child,0.)
            result = [0.,0.,0.]
            for a,b,scale,weight in zip(old,new,scales,weights):
                x,y,z = _point(src[i],inverses[a])
                point = _point((-z,y,x*scale),binds[b])
                for k in range(3):
                    result[k] += point[k]*weight/sum(weights)
            model['positions'].append(result)
            for key in ('uv','uv1','colors'):
                model[key].append(source[key][i])
            model['source_vertices'].append(i)
            model['sides'].append(side)
        for ids,weights in _finger_weights(source,used,triangles,inverses,old,new,child,side,scales[2],target,binds):
            model['bones'].append(ids)
            model['weights'].append(weights)
        model['triangles'].extend(tuple(mapping[i] for i in tri) for tri in triangles)
        # Only the proximal cut is open. Put it at the original POV arm extent
        # and cap it; no fingertip or wrist triangles are discarded.
        vertices,boundary = _boundary(triangles,source['positions'])
        if len(boundary) != 11:
            raise ValueError('Unexpected proximal arm boundary')
        boundary_ids = sorted({i for edge in boundary for i in edge})
        end = min(_point(p,target['inverse'][new[0]])[2] for p,w in zip(target['positions'],target['weights'])
                  if w.get(new[0],0.) > .98)
        for i in used:
            if vertices[i] in boundary_ids:
                local = list(_point(model['positions'][mapping[i]],target['inverse'][new[0]]))
                local[2] = end
                model['positions'][mapping[i]] = _point(local,binds[new[0]])
                model['bones'][mapping[i]],model['weights'][mapping[i]] = [new[0],0,0,0],[255,0,0,0]
        caps = _cap(boundary,mapping,model['positions'],target['inverse'][new[0]])
        model['cap_faces'].extend(range(len(model['triangles']),len(model['triangles'])+len(caps)))
        model['triangles'].extend(caps)
        model['metrics'].append(dict(side=side,source_vertices=len(used),source_triangles=len(triangles),
                                     bind_scales=scales,cap_triangles=len(caps),proximal_triangles_retriangulated=len(ears)))
    return model


def _chunk(tag, data):
    return struct.pack('<3I',tag,len(data),0x1803ffff)+data


def _one(raw, tag):
    found = [part for kind,part in rw.chunks(raw,12) if kind == tag]
    if len(found) != 1:
        raise ValueError('Unexpected hand container layout')
    return found[0]


def _normals(model):
    normals = [[0.,0.,0.] for _ in model['positions']]
    for tri in model['triangles']:
        a,b,c = (model['positions'][i] for i in tri)
        ab,ac = [b[k]-a[k] for k in range(3)],[c[k]-a[k] for k in range(3)]
        cross = (ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0])
        for i in tri:
            for k in range(3):
                normals[i][k] += cross[k]
    # UV seams duplicate vertices. Accumulate their shared surface normal so
    # the original atlas boundaries cannot become visible lighting seams.
    groups = {}
    keys = [tuple(round(v,6) for v in p) for p in model['positions']]
    for key,normal in zip(keys,normals):
        total = groups.setdefault(key,[0.,0.,0.])
        for k in range(3):
            total[k] += normal[k]
    packed = []
    for key in keys:
        normal = groups[key]
        length = math.sqrt(sum(v*v for v in normal))
        if length < 1e-12:
            raise ValueError('Degenerate arm vertex normal')
        x,y,z = [v/length for v in normal]
        packed.append((round(x*1023)&2047)|((round(y*1023)&2047)<<11)|((round(z*511)&1023)<<22))
    return packed


def _emit(model, original, spectral, source, target):
    count, triangles = len(model['positions']),len(model['triangles'])
    indices = [i for tri in model['triangles'] for i in tri]
    align = lambda n:(n+15)&~15
    header = bytearray(36+24+16+align(2*len(indices)))
    offset = align(24+36+24)-24
    struct.pack_into('<IHH7I',header,0,len(header),1,1,5,count,36,0,0,0,0)
    struct.pack_into('<6I',header,36,min(indices),max(indices)-min(indices)+1,len(indices),offset+24,0,0)
    struct.pack_into('<'+str(len(indices))+'H',header,offset,*indices)
    vertices = b''.join(struct.pack('<3fII4f',*p,n,c,*uv,*uv1) for p,n,c,uv,uv1 in zip(
        model['positions'],_normals(model),model['colors'],model['uv'],model['uv1']))
    native = _chunk(0x510,_chunk(1,struct.pack('<I',5)+header+vertices))
    prefix = bytearray(target['skin_prefix'])
    palette,reverse = struct.unpack_from('<256i',prefix,8),struct.unpack_from('<256i',prefix,1032)
    if struct.unpack_from('<4I',prefix,2056)[0:2] != (20,4):
        raise ValueError('Unsupported first-person skin palette')
    struct.pack_into('<I',prefix,2064,0)
    skin = bytearray(prefix)
    for bones,weights in zip(model['bones'],model['weights']):
        ids = []
        for bone,weight in zip(bones,weights):
            index = reverse[bone]
            if weight and (index < 0 or palette[index] != bone):
                raise ValueError('Unmapped first-person bone')
            ids.append(max(0,index)*3)
        skin += bytes(weights)+struct.pack('<4H',*ids)
    skin += target['inverse_bytes']+bytes(12)
    materials = [part for tag,part in rw.chunks(_one(source['geometry'],8),12) if tag == 7]
    if len(materials) != 3 or b'BossCassidy_body_X\0' not in materials[2] or b'stripe_X\0' not in materials[2]:
        raise ValueError('Original spectral skin material differs')
    material = _chunk(8,_chunk(1,struct.pack('<2I',1,0xffffffff))+materials[2])
    geom = bytearray(_one(source['geometry'],1)[12:])
    struct.pack_into('<2I',geom,4,triangles,count)
    center = [(min(p[k] for p in model['positions'])+max(p[k] for p in model['positions']))/2 for k in range(3)]
    struct.pack_into('<4f',geom,16,*center,max(math.dist(center,p) for p in model['positions']))
    mesh = _chunk(0x50e,struct.pack('<5I',0,1,len(indices),len(indices),0))
    extension = _chunk(3,mesh+native+_chunk(0x511,struct.pack('<I',0x01005545))+_chunk(0x116,_chunk(1,skin)))
    geometry = _chunk(15,_chunk(1,geom)+material+extension)
    geolist = _chunk(26,_chunk(1,struct.pack('<I',1))+geometry)
    old_clump = next(part for tag,part in rw.chunks(original) if tag == 0x10)
    boss_clump = next(part for tag,part in rw.chunks(spectral) if tag == 0x10)
    body_atomic = next(part for tag,part in rw.chunks(boss_clump,12)
                       if tag == 20 and struct.unpack_from('<I',_one(part,1),16)[0] == 2)
    parts = []
    for tag,part in rw.chunks(old_clump,12):
        if tag == 26:
            part = geolist
        elif tag == 20:
            # Keep the player's frame binding, but the boss's skin-MatFX
            # pipeline2 and atomic enable flag are required for the dual UVs.
            part = rw.rebuild(part,_one(part,1)+_one(body_atomic,3))
        parts.append(part)
    clump = rw.rebuild(old_clump,b''.join(parts))
    dictionaries = [part for tag,part in rw.chunks(spectral) if tag == 0x16]
    if len(dictionaries) != 2:
        raise ValueError('Missing original spectral distance dictionary')
    dictionary = iter(dictionaries)
    return b''.join(next(dictionary) if tag == 0x16 else clump if tag == 0x10 else part
                    for tag,part in rw.chunks(original))


def bake(original, spectral):
    """Return the locally derived native model and its conversion summary."""
    if hashlib.sha256(original).hexdigest() != rw.SOURCE_SHA or hashlib.sha256(spectral).hexdigest() != SOURCE_SHA:
        raise ValueError('Unsupported original hand sources')
    source,target = _geometry(spectral,2),_geometry(original,0)
    model = _adapt(source,target)
    output = _emit(model,original,spectral,source,target)
    return output,dict(vertices=len(model['positions']),triangles=len(model['triangles']),
                       arms=model['metrics'],original_uv_sets=2,original_material=True,
                       original_player_rig=True,skin_pipeline=2)


