"""Add two chest helpers without reusing the banshee's animated dress bones."""
import hashlib
import math
import struct

import character_animation as animation
import character_boss as boss
import character_repaint as rw
import character_secondary as secondary
import character_weapon_pose as pose

MODEL = 'characters/banshee/base_banshee'
SOURCE_SHA = 'e2692e68d1893c4fe3d2a81a4b81c2cf00ea9f71a082b3f14a1e42490abf46f9'
CENTERS = ((.07, .35, .11), (-.07, .35, .11))


def influence(point, side):
    center = CENTERS[side]
    if point[0]*center[0] <= 0:
        return 0.
    distance = sum(((p-c)/r)**2 for p, c, r in zip(point, center, (.09, .10, .12)))
    return .65*max(0., 1.-distance)**2*min(1., max(0., (abs(point[0])-.012)/.035))


def expand_animation(data):
    flags, parts = boss.sections(data, 32)
    out = bytearray(data[:24])
    struct.pack_into('<I', out, 8, 34)
    struct.pack_into('<I', out, 20, flags | 1)
    mask = parts.get(1)
    out += struct.pack('<I', 34)+(data[mask['keys']:mask['end']] if mask else bytes(128))+struct.pack('<2I', 1, 1)
    for bit, _ in animation.ORDER:
        if bit not in parts or bit == 1:
            continue
        row = parts[bit]
        out += data[row['start']:row['keys']]
        if bit in (4, 8, 32):
            out += struct.pack('<2I', boss.MISSING, boss.MISSING)
        out += data[row['keys']:row['end']]
    boss.sections(out, 34)
    return bytes(out)


def model(data):
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise ValueError('Unexpected original banshee model')
    rig, _, _ = boss.rig(data, 32)
    parents = [rig[i]['parent_bone'] for i in range(32)]
    flags = secondary._flags(parents+[0, 0])
    local = {i: (tuple(tuple(rig[i]['rotation'][j:j+3]) for j in (0,3,6)), rig[i]['translation']) for i in range(32)}
    world = pose.world(local, dict(enumerate(parents)))
    helper = pose.mul(world[2], pose.inverse(world[0]))
    helper_pose = animation._to_quaternion(helper[0])+helper[1]
    frame = struct.pack('<12f2i', *(v for row in helper[0] for v in row), *helper[1], rig[0]['frame'], 0)
    changed = [0, 0]

    def rebuild(raw):
        out = []
        for tag, part in rw.chunks(raw):
            if tag == 14:
                chunks = rw.chunks(part, 12)
                header = bytearray(chunks[0][1][12:]);struct.pack_into('<I', header, 0, 35)
                payload = rw.rebuild(chunks[0][1], header+frame*2)
                payload += rebuild(b''.join(p for _, p in chunks[1:]))
                version = struct.unpack_from('<I', chunks[1][1], 8)[0]
                for bone in (32, 33):
                    extension = struct.pack('<6I', 0x11e, 12, version, 0x100, bone, 0)
                    payload += struct.pack('<3I', 3, len(extension), version)+extension
                part = rw.rebuild(part, payload)
            elif tag == 0x11e and struct.unpack_from('<I', part, 20)[0]:
                payload = bytearray(part[12:]);struct.pack_into('<I', payload, 8, 34)
                payload += struct.pack('<6I', 32, 32, flags[32], 33, 33, flags[33])
                for bone in range(32):struct.pack_into('<I', payload, 28+12*bone, flags[bone])
                part = rw.rebuild(part, payload)
            elif tag == 15:
                rows = list(boss._records(part, 12, len(part), 15))
                ns, ne = next((a,z) for t,a,z,p in rows if t == 0x510)
                _, start, end = next(animation._chunks(part, ns, ne))
                size = struct.unpack_from('<I', part, start+4)[0]
                count, stride = struct.unpack_from('<II', part, start+16)
                vertices = start+4+size
                if vertices+count*stride != end:
                    raise ValueError('Unexpected banshee vertices')
                points = [struct.unpack_from('<3f', part, vertices+i*stride) for i in range(count)]
                def skin_rebuild(raw):
                    output = []
                    for kind, item in rw.chunks(raw):
                        if kind == 0x116:
                            entries = rw.chunks(item, 12)
                            if len(entries) != 1 or entries[0][0] != 1:
                                raise ValueError('Unexpected banshee skin')
                            old = entries[0][1][12:]
                            header = bytearray(old[:2072]);used, width, _, skin_stride = struct.unpack_from('<4I', old, 2056)
                            if struct.unpack_from('<II', old) != (5,32) or (width,skin_stride) != (2,6) or len(old) != 2072+6*count+32*64+12:
                                raise ValueError('Unexpected banshee skin dimensions')
                            palette = struct.unpack_from('<256i', old, 8)
                            inverse = old[2072+6*count:2072+6*count+32*64]
                            body = count == 749
                            struct.pack_into('<I', header, 4, 34)
                            if body:
                                if used != 26 or 2 not in palette[:used]:raise ValueError('Banshee chest donor missing')
                                struct.pack_into('<2i', header, 8+4*used, 32,33)
                                struct.pack_into('<2i', header, 1032+4*32, used,used+1)
                                struct.pack_into('<II', header, 2056, used+2,4)
                                struct.pack_into('<I', header, 2068,12)
                            weights = bytearray()
                            for vertex, point in enumerate(points):
                                at=2072+vertex*6;values=list(old[at:at+2]);ids=list(struct.unpack_from('<2H',old,at+2))
                                if sum(values)!=255 or any(i%3 or i//3>=used for i,w in zip(ids,values) if w) or not all(math.isfinite(v) for v in point):
                                    raise ValueError('Invalid banshee vertex weights')
                                if body:
                                    values += [0,0];ids += [0,0]
                                    for side in range(2):
                                        for source in range(2):
                                            if palette[ids[source]//3] != 2:continue
                                            amount=round(values[source]*influence(point,side))
                                            if amount:
                                                values[source]-=amount;values[2+side]=amount;ids[2+side]=(used+side)*3;changed[side]+=1
                                weights += bytes(values)+struct.pack('<'+'H'*len(ids),*ids)
                            tail=inverse+inverse[128:192]*2+old[-12:]
                            item=rw.rebuild(item,rw.rebuild(entries[0][1],header+weights+tail))
                        elif kind in boss.CONTAINERS:
                            item=rw.rebuild(item,skin_rebuild(item[12:]))
                        output.append(item)
                    return b''.join(output)
                part=rw.rebuild(part,skin_rebuild(part[12:]))
            elif tag == 0x1b:
                old=part[12:]
                if struct.unpack_from('<4I',old)!=(0x100,1,65,0) or len(old)!=20+65*36:
                    raise ValueError('Unexpected banshee bind animation')
                header=bytearray(old[:20]);struct.pack_into('<I',header,8,69)
                keys=[bytearray(old[20+36*i:56+36*i]) for i in range(65)]
                for key in keys:
                    previous=struct.unpack_from('<I',key,32)[0]
                    if previous<65*36 and previous%36==0:
                        index=previous//36;struct.pack_into('<I',key,32,(index+(2 if index>=32 else 0)+(2 if index>=64 else 0))*36)
                extra=[]
                for half in range(2):
                    time=struct.unpack_from('<f',keys[32*half])[0]
                    extra.append(b''.join(struct.pack('<8fI',time,*helper_pose,struct.unpack_from('<I',keys[0],32)[0] if half==0 else (32+side)*36) for side in range(2)))
                part=rw.rebuild(part,header+b''.join(keys[:32])+extra[0]+b''.join(keys[32:64])+extra[1]+keys[64])
            elif tag in boss.CONTAINERS:
                part=rw.rebuild(part,rebuild(part[12:]))
            out.append(part)
        return b''.join(out)
    result=rebuild(data)
    boss.rig(result,34)
    if min(changed)<6:raise ValueError(f'Banshee chest coverage missing: {changed}')
    return result


def resources(entries, read):
    outputs={MODEL+'.rx1':model(read(MODEL+'.rx1'))}
    joints=read(MODEL+'.jlist')
    if len(joints.decode('ascii').splitlines())!=32:raise ValueError('Unexpected banshee joints')
    outputs[MODEL+'.jlist']=joints.rstrip()+b'\r\n    BansheeChestLeft\r\n    BansheeChestRight\r\n'
    clips=[name for name in entries if name.startswith('characters/banshee/') and name.endswith('.sanm')]
    if len(clips)!=44:raise ValueError('Unexpected banshee animation inventory')
    for name in clips:outputs[name]=expand_animation(read(name))
    return outputs
