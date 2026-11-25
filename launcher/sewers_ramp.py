"""Add complete collision-only sewer banks using original muddy floor shading."""
import hashlib, math, struct
import character_repaint as rw
RESOURCE='levels/singleplayer/m09_torturemaze/m09_d/m09_d_alpha.rx1'
COLLISION=RESOURCE.replace('_alpha.rx1','_collision.btkl')
SOURCE_SHA='d695ad09f6a06645bd10480252bc45e72a3e053ff7564aa50c59c92ae50e88dc'
COLLISION_SHA='c264143386cac749562450ad655ddbfc0d5dee611de7d3e3b83415a403b50e0e'
BANKS={213600:(1186,1345,2034),226468:(1139,1763)}

def _native(atomic):
    geo=next(p for t,p in rw.chunks(atomic,12) if t==15)
    ext=next(p for t,p in rw.chunks(geo,12) if t==3)
    native=next(p for t,p in rw.chunks(ext,12) if t==0x510)
    return rw.chunks(native,12)[0][1][12:]

def _triangles(indices):
    for j in range(2,len(indices)):
        a,b,c=indices[j-2:j+1]
        if len({a,b,c})==3:yield (b,a,c) if j%2 else (a,b,c)

def _sample(point,vertices,triangles):
    best=None
    x,_,z=point
    for ids in triangles:
        a,b,c=[vertices[i] for i in ids]
        dx1,dz1,dx2,dz2=b[0]-a[0],b[2]-a[2],c[0]-a[0],c[2]-a[2]
        det=dx1*dz2-dx2*dz1
        if abs(det)<1e-8:continue
        v=((x-a[0])*dz2-(z-a[2])*dx2)/det
        w=(dx1*(z-a[2])-dz1*(x-a[0]))/det
        weights=(1-v-w,v,w)
        height=sum(q*p[1] for q,p in zip(weights,(a,b,c)))
        score=sum(max(0,-q) for q in weights)*1000+abs(height-point[1])
        if best is None or score<best[0]:best=(score,weights,(a,b,c))
    if best is None:raise ValueError('No source floor triangle')
    _,weights,points=best
    uv=[sum(w*p[k] for w,p in zip(weights,points)) for k in (4,5)]
    clamped=[max(0,min(1,w)) for w in weights];total=sum(clamped)
    color=sum(round(sum(w*((p[3]>>s)&255) for w,p in zip(clamped,points))/total)<<s for s in (0,8,16,24))
    return struct.pack('<3fI2f',*point,color,*uv)

def repair(data,collision):
    if hashlib.sha256(data).hexdigest()!=SOURCE_SHA or hashlib.sha256(collision).hexdigest()!=COLLISION_SHA:
        raise ValueError('Unsupported original Sewers resources')
    count=struct.unpack_from('<I',collision)[0];index_offset=8+count*12
    output=[];offset=0
    for tag,atomic in rw.chunks(data):
        old_size=len(atomic)
        if offset in BANKS:
            if tag!=0x14 or b'mud_puddle_01\0' not in atomic:raise ValueError('Unexpected floor material')
            points=[]
            for first in BANKS[offset]:
                for triangle in range(first,first+4):
                    ids=struct.unpack_from('<3H',collision,index_offset+triangle*6)
                    tri=[struct.unpack_from('<3f',collision,4+i*12) for i in ids]
                    ny=(tri[1][2]-tri[0][2])*(tri[2][0]-tri[0][0])-(tri[1][0]-tri[0][0])*(tri[2][2]-tri[0][2])
                    if ny<=0:raise ValueError('Downward Sewers slope')
                    points.extend(tri)
            atomic=_append(atomic,points)
        output.append(atomic);offset+=old_size
    return b''.join(output)

def _append(atomic,points):
    native=_native(atomic);header=list(struct.unpack_from('<19I',native))
    if header[0]!=5 or header[3]!=6 or header[5]!=24 or header[11]!=header[4]:raise ValueError('Unexpected floor buffer')
    count,stride,old_size=header[4],header[5],header[1]+4
    vertices=[struct.unpack_from('<3fI2f',native,old_size+i*stride) for i in range(count)]
    indices=list(struct.unpack_from('<'+'H'*header[12],native,76));old_count=len(indices)
    original_triangles=list(_triangles(indices))
    additions=b''.join(_sample(p,vertices,original_triangles) for p in points)
    for start in range(count,count+len(points),3):
        a,b,c=start,start+1,start+2
        if len(indices)%2:a,b=b,a
        indices.extend((indices[-1],a,a,b,c))
    new_size=old_size+((2*(len(indices)-old_count)+15)//16)*16
    padding=new_size-76-len(indices)*2
    header[1]=new_size-4;header[4]=header[11]=count+len(points);header[12]=len(indices)
    new_native=struct.pack('<19I',*header)+struct.pack('<'+'H'*len(indices),*indices)+bytes(padding)+native[old_size:]+additions
    def rebuild(data,parent):
        result=[]
        for tag,part in rw.chunks(data):
            payload=part[12:]
            if tag==1 and parent==15:
                payload=bytearray(payload);sphere=struct.unpack_from('<4f',payload,16)
                if any(math.dist(p,sphere[:3])>sphere[3] for p in points):raise ValueError('Bank exceeds original bounds')
                triangles,n=struct.unpack_from('<II',payload,4)
                if n!=count:raise ValueError('Floor count mismatch')
                struct.pack_into('<II',payload,4,triangles+len(points)//3,n+len(points))
            elif tag==0x50e:
                flags,meshes,total,size,material=struct.unpack('<5I',payload)
                if (flags,meshes,total,size)!=(1,1,old_count,old_count):raise ValueError('Unexpected floor partition')
                payload=struct.pack('<5I',flags,meshes,len(indices),len(indices),material)
            elif tag==1 and parent==0x510:payload=new_native
            elif tag in (0x14,15,3,0x510):payload=rebuild(payload,tag)
            result.append(rw.rebuild(part,payload))
        return b''.join(result)
    return rebuild(atomic,None)


def prepare_archive(source, target, cancel=lambda: None):
    import mmap
    import character_archive
    from pathlib import Path
    with Path(source).open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        rows = {row['name']: row for row in character_archive.read(raw)['entries']}
        def read(name):
            row = rows[name]
            return raw[row['offset']:row['offset'] + row['size']]
        repaired = repair(read(RESOURCE), read(COLLISION))
    character_archive.compose_file(source, {RESOURCE: repaired}, target, cancel)
