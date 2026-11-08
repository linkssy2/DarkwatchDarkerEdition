"""Reuse verified prepared resources while deriving a pinned character update."""
from contextlib import ExitStack
import copy
import gzip
import hashlib
import io
import json
import mmap
import os
from pathlib import Path
import re
import stat
import struct
import tempfile

import character_archive as pck
import character_assets as art
import character_reload
import character_starter_reload
import character_weapon_hold
import character_weapon_pose
import third_person_animation as animation
import enemy_blood

RECIPE_NAME = 'character-update.json.gz'
RECIPE_SHA256 = 'e3d15b5e2ae6999d3be290b5ea88e194ec18627015483c03f1d657168dbbae0d'
CHUNK = 4 * 1024 * 1024


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid character update extent')
    return value


def pin(value):
    integer(value['size'], 1, 0xffffffff)
    if not isinstance(value['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['sha256']):
        raise ValueError('Invalid character update identity')


def digest(raw, cancel, start=0, size=None):
    size = len(raw)-start if size is None else size
    result = hashlib.sha256()
    for offset in range(start, start+size, CHUNK):
        cancel()
        result.update(raw[offset:min(offset+CHUNK, start+size)])
    return result.hexdigest()


def recipe(payload, metadata):
    path = Path(payload)/RECIPE_NAME
    if path.stat().st_size > 2*1024*1024:
        raise ValueError('Character update recipe is too large')
    packed = path.read_bytes()
    if pck.sha(packed) != RECIPE_SHA256:
        raise ValueError('Character update recipe changed')
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        raw = stream.read(16*1024*1024+1)
    if len(raw) > 16*1024*1024:
        raise ValueError('Character update recipe expands too far')
    result = json.loads(raw)
    validate_recipe(result, metadata)
    return result


def validate_recipe(result, metadata):
    if (result['schema_version'] != 1 or result['from_revision'] != 'character-tala-presentation-v26' or
            result['to_revision'] != metadata['content_revision'] or
            set(result['archives']) != set(metadata['installed'])):
        raise ValueError('Unsupported character update recipe')
    suffixes = result['suffixes']
    dependencies = result['dependencies']
    if not isinstance(dependencies,list) or len(dependencies)>20000:
        raise ValueError('Invalid character update dependency list')
    for name,kind in dependencies:
        pck.canonical(name)
        if not isinstance(kind,str) or not 0<len(kind)<128 or not kind.isascii():
            raise ValueError('Invalid character update reference type')
    if not isinstance(suffixes, list) or len(suffixes) > 1000:
        raise ValueError('Invalid character update reference list')
    for suffix in suffixes:
        if not isinstance(suffix, list) or len(suffix) > 20000:
            raise ValueError('Character update reference list is too large')
        for dependency in suffix:
            integer(dependency,0,len(dependencies)-1)
    for name, item in result['archives'].items():
        pin(item['before'])
        pin(item['after'])
        if item['after'] != metadata['installed'][name]:
            raise ValueError('Character update target differs')
        if item.get('reuse'):
            if item['before'] != item['after']:
                raise ValueError('Character update reuse identity differs')
            continue
        pin(item['prefix'])
        prefix = integer(item['prefix']['size'], 1, min(item['before']['size'],item['after']['size']))
        index = item['index']
        start = integer(index['start'], prefix, item['after']['size']-40)
        capacity = integer(index['capacity'], 64, 1048576)
        if capacity & (capacity-1) or len(index['entries']) > capacity-2:
            raise ValueError('Invalid character update index capacity')
        entries = {}
        slots = set()
        for entry in index['entries']:
            path = pck.canonical(entry['name'])
            offset = integer(entry['offset'], 0, start)
            size = integer(entry['size'], 1, start-offset)
            if offset<prefix<offset+size:
                raise ValueError('Character update resource crosses its retained prefix')
            slot = integer(entry['slot'], 0, capacity-1)
            integer(entry['next'], 1, capacity-1)
            if path != entry['name'] or path in entries or slot in slots:
                raise ValueError('Duplicate character update index record')
            entries[path] = entry
            slots.add(slot)
        resources = item['resources']
        if len(resources) > len(entries):
            raise ValueError('Invalid character update resource count')
        seen = set()
        position = prefix
        for resource in resources:
            path = pck.canonical(resource['name'])
            pin(resource)
            entry = entries[path]
            if (path != resource['name'] or path in seen or resource['size'] != entry['size'] or
                    not position <= entry['offset'] <= position+2047):
                raise ValueError('Invalid character update payload ordering')
            position = entry['offset']+entry['size']
            seen.add(path)
            if resource['source'] not in ('previous','generated','preload'):
                raise ValueError('Invalid character update resource source')
            if resource['source'] == 'preload':
                if not re.fullmatch('[0-9a-f]{64}',resource['before_sha256']):
                    raise ValueError('Invalid previous character preload identity')
                integer(resource['keep_rows'],0,19999)
                integer(resource['suffix'],0,len(suffixes)-1)
        if start-position not in range(2048) or {n for n,e in entries.items() if e['offset']>=prefix} != seen:
            raise ValueError('Incomplete character update payload coverage')


def preload(raw, keep, suffix):
    """Keep a canonical unchanged row prefix and append authored references."""
    if len(raw)<6 or raw[:4] != b'\x01\0\0\0':
        raise ValueError('Unsupported previous character preload')
    count = struct.unpack_from('<H',raw,4)[0]
    ends = [6]
    position = 6
    if count>=20000:
        raise ValueError('Previous character preload has too many strings')
    for _ in range(count):
        if position+2>len(raw):
            raise ValueError('Truncated previous character preload strings')
        length = struct.unpack_from('<H',raw,position)[0]
        position += 2+length
        if length>=4096 or position>len(raw):
            raise ValueError('Invalid previous character preload strings')
        ends.append(position)
    body=raw[position:]
    if len(body)<16:
        raise ValueError('Truncated previous character preload')
    root,attrs,children,data,data_attrs,rows=struct.unpack_from('<6H',body)
    if ((root,attrs,children,data,data_attrs)!=(0,0,1,1,0) or rows<keep or
            len(body)!=16+24*rows or body[-4:]!=b'\xff'*4):
        raise ValueError('Unsupported previous character preload rows')
    used=1
    for row in struct.iter_unpack('<12H',body[12:12+keep*24]):
        used=max(used,row[0],row[3],row[6],row[7],row[10])
    if used>=count:
        raise ValueError('Previous character preload index is out of range')
    prefix=(raw[:4]+struct.pack('<H',used+1)+raw[6:ends[used+1]]+
            body[:10]+struct.pack('<H',keep)+body[12:12+keep*24]+body[-4:])
    return art.append_resource_bytes(prefix,suffix)[0]


def starter_fanning(raw, previous, original, model, locator, basis, actor, offsets):
    """Rebuild starter fanning from retained pre-grip clips, never fitted grips."""
    tree = art.decode(animation.gate_redeemer_aim(raw))
    groups = animation.groups(tree)
    def flags(node):
        return {row['attributes']['Flag'] for row in node['children'] if row['name']=='Modifier'}
    shots = [node for node in groups['Weapon Shoot']['children'] if
             node['attributes'].get('AnimationID')=='ALT_SHOOT' and flags(node)=={'PISTOL'}]
    if len(shots)!=1:
        raise ValueError('Missing retained starter fanning reference')
    shot = shots[0]['attributes']['Name']
    normalized = art.norm(shot)
    prefix = normalized[:-len(character_weapon_pose._original(normalized))]
    native = animation.groups(art.decode(original(animation.NATIVE_FULL)))['Pistol Aim']
    paths = {node['attributes']['AnimationID']:node['attributes']['Name']
             for node in native['children'] if flags(node)=={'REVOLVER','AIMING','OUT_OF_VEHICLE'}}
    if set(paths)!={'AIM_POSE_UP','AIM_POSE_DOWN','AIM_POSE_LEFT','AIM_POSE_RIGHT'}:
        raise ValueError('Incomplete original fanning directions')
    subset = copy.deepcopy(tree)
    subset['children'] = [group for group in subset['children'] if group['name']=='AnimationGroup' and
                          group['attributes']['ToolName'] in ('Pistol Aim','Weapon Shoot')]
    subset['attributes']['GroupCount'] = '2'
    for group in subset['children']:
        aim = group['attributes']['ToolName']=='Pistol Aim'
        group['children'] = [node for node in group['children'] if
            (('ALT_WEAPON_OPERATE' in flags(node)) if aim else node['attributes'].get('AnimationID')=='ALT_SHOOT') and
            flags(node)&{'PISTOL','REVOLVER'}]
        group['attributes']['KeyedAnimationCount'] = str(len(group['children']))
        for node in group['children']:
            native_path = paths[node['attributes']['AnimationID']] if aim else shot
            node['attributes']['Name'] = prefix+art.norm(native_path) if aim and prefix else native_path
    selected = {key:value for key,value in offsets.items() if key[0]==actor and key[1] in ('BasicPistol','Revolver')}
    fitted, added = character_weapon_pose.prepare_grip_table(
        art.encode(subset),previous,original,model,locator,basis,actor,selected)
    referenced = set()
    for group in art.decode(fitted)['children']:
        for node in group['children']:
            if 'PISTOL' not in flags(node):
                continue
            target = next(row for row in groups[group['attributes']['ToolName']]['children'] if
                row['attributes'].get('AnimationID')==node['attributes']['AnimationID'] and flags(row)==flags(node))
            target['attributes']['Name'] = node['attributes']['Name']
            referenced.add(art.norm(node['attributes']['Name'])+'.sanm')
    changed = {}
    for path,data in added.items():
        if path not in referenced:
            continue
        try:
            retained = previous(path)
        except KeyError:
            retained = None
        if data != retained:
            changed[path] = data
    return art.encode(tree), changed


def starter_reload(raw, previous, original, model, locator, basis, actor, offsets):
    """Rebuild the five starter phases from the retained unsolved body action."""
    tree = art.decode(raw)
    groups = animation.groups(tree)
    def flags(node):
        return {row['attributes']['Flag'] for row in node['children'] if row['name']=='Modifier'}
    def key(node):
        return node['attributes'].get('AnimationID'), frozenset(flags(node))
    current = [node for node in groups['Reload Pistol']['children'] if 'PISTOL' in flags(node)]
    expected = {('RELOAD',frozenset(('PISTOL','OUT_OF_VEHICLE')))} | {
        (action,frozenset(('PISTOL','OUT_OF_VEHICLE',stance)))
        for action in ('PRERELOAD','POSTRELOAD') for stance in ('STAND','CROUCH')}
    if len(current)!=5 or {key(node) for node in current}!=expected:
        raise ValueError('Unexpected retained starter reload phases')
    ready = [node for node in groups['Alert Poses UB']['children'] if 'PISTOL' in flags(node)]
    if len(ready)!=1:
        raise ValueError('Missing retained starter reload ready pose')
    path = art.norm(ready[0]['attributes']['Name'])
    native_path = character_weapon_pose._original(path)
    if not native_path.endswith('/dwagentmale_readystand_ub'):
        raise ValueError('Unrecognized retained starter reload basis')
    prefix = path[:-len(native_path)]
    native = animation.groups(art.decode(original(animation.NATIVE_FULL)))['Reload Pistol']
    shared = [node for node in native['children'] if
        node['attributes'].get('AnimationID')=='RELOAD' and
        flags(node)=={'PISTOL','REVOLVER','OUT_OF_VEHICLE'}]
    if len(shared)!=1:
        raise ValueError('Missing original shared pistol reload')
    shared = copy.deepcopy(shared[0])
    shared['attributes']['Name'] = prefix+art.norm(shared['attributes']['Name'])
    subset = copy.deepcopy(tree)
    subset['children'] = [copy.deepcopy(groups[name]) for name in
        ('Alert Poses UB','Crouch Alert Poses','Reload Pistol')]
    subset['attributes']['GroupCount'] = '3'
    subset['children'][-1]['children'] = [shared]
    subset['children'][-1]['attributes']['KeyedAnimationCount'] = '1'
    fitted, added = character_starter_reload.prepare_table(
        art.encode(subset),previous,original,model,locator,basis,
        offsets.get((actor,'BasicPistol'),(0.,0.))[0],actor=actor)
    completed = {key(node):node for node in animation.groups(art.decode(fitted))['Reload Pistol']['children']
                 if 'PISTOL' in flags(node)}
    if set(completed)!=expected:
        raise ValueError('Incomplete rebuilt starter reload phases')
    for node in current:
        node['attributes']['Name'] = completed[key(node)]['attributes']['Name']
    return art.encode(tree), added


def body_resources(previous, source):
    """Derive new held-motion and mechanical actions from completed v26 poses."""
    output = {}
    actors = art.decode(previous(animation.CHARACTERS))
    aliases = {}
    offsets = character_weapon_pose.read_grip_offsets()
    def read(path):
        return output[path] if path in output else previous(path)
    for index,name in enumerate((*animation.PLAYERS,*animation.COOP_PLAYERS),1):
        source.report(f'Updating animations: character {index}/20 - reusing completed poses')
        actor=art.child(actors,name)
        def field(component,key):
            return art.child(art.child(actor,component),key)['attributes']['value']
        model=previous(art.norm(field('AlternativeModelsRenderComponent','m_modelResourcePath'))+'.rx1')
        locator=previous(art.norm(field('LocatorAttachmentComponent','m_locatorFileName'))+'.bllist')
        mapping={row['attributes']['key']:art.norm(row['attributes']['value'])+'.bxml'
                 for row in art.child(art.child(actor,'AnimationComponent'),'m_AnimationFiles')['children']}
        aliases[name]=mapping
        path=animation.JERICHO_FULL if mapping['Multi']==animation.NATIVE_FULL else mapping['Multi']
        basis=character_weapon_pose.a.STORM if name in animation.COOP_PLAYERS and name!='JerichoCoop' else character_weapon_pose.a.CHAZ
        table,added=starter_fanning(previous(path),previous,source.read,model,locator,basis,name,offsets)
        output.update(added)
        table,added=starter_reload(table,previous,source.read,model,locator,basis,name,offsets)
        output.update(added)
        table,added=character_weapon_hold.prepare_aimed_motion_table(table,read,source.read,model,locator,basis,name,offsets)
        output.update(added)
        table,added=character_reload.prepare_mechanical_table(table,read,source.read,model,locator,basis,name,offsets)
        output.update(added)
        output[path]=table
    for name in animation.PLAYERS:
        mapping=aliases[name]
        full=animation.JERICHO_FULL if mapping['Multi']==animation.NATIVE_FULL else mapping['Multi']
        old=animation.groups(art.decode(previous(mapping['NotMulti'])))
        completed=art.decode(output[full])
        groups=animation.groups(completed)
        completed['children']=[row for row in completed['children'] if row['attributes'].get('ToolName') not in animation.EXCLUDED_GROUPS]
        completed['children'].extend(copy.deepcopy(old[group]) for group in animation.PRESERVED_GROUPS)
        completed['attributes']['GroupCount']=str(len(groups)-len(animation.EXCLUDED_GROUPS)+len(animation.PRESERVED_GROUPS))
        output[mapping['NotMulti']]=art.encode(completed)
    output[animation.CHARACTERS] = art.encode(enemy_blood.append(actors))
    # Mechanical fitting replaces some temporary shoulder clips. Match the full
    # producer: retain only animations referenced by the completed body tables.
    referenced={clip+'.sanm' for path,data in output.items() if path.endswith('.bxml')
                for clip in animation.clips(data)}
    return {path:data for path,data in output.items() if not path.endswith('.sanm') or path in referenced}


def index_bytes(item, previous):
    index=item['index']
    capacity=index['capacity']
    mask=capacity-1
    rows=[[0,0,0] for _ in range(capacity)]
    old={entry['name']:entry for entry in previous['entries']}
    entries=sorted(index['entries'],key=lambda e:e['slot'])
    for entry in entries:
        rows[entry['slot']]=[(pck.path_hash(entry['name'][::-1]) & ~mask)|entry['next'],entry['offset'],entry['size']]
    result=bytearray(struct.pack('<4I',capacity,len(entries),mask,0))
    for row in rows:
        result.extend(struct.pack('<QII',*row))
    for entry in entries:
        if pck.lookup(rows,mask,entry['name'])!=entry['slot']:
            raise ValueError('Invalid character update lookup chain')
        pointer=0
        if entry['offset']<item['prefix']['size']:
            previous_entry=old[entry['name']]
            if (previous_entry['offset'],previous_entry['size'])!=(entry['offset'],entry['size']):
                raise ValueError('Character update prefix entry moved')
            pointer=previous_entry['pointer']
        name=entry['name'].encode('ascii')
        result.extend(struct.pack('<II',pointer,len(name)))
        result.extend(name)
    footer=bytearray(previous['footer'])
    struct.pack_into('<I',footer,32,index['start'])
    result.extend(footer)
    return result


def try_prepare(assets,payload,previous_assets,metadata,cancel,progress):
    import character_content
    assets,previous_assets=Path(assets),Path(previous_assets)
    if assets.resolve()==previous_assets.resolve():
        raise ValueError('Character update requires a separate stage')
    plan=recipe(payload,metadata)
    try:
        root_info=previous_assets.lstat()
    except OSError:
        return False
    if (not stat.S_ISDIR(root_info.st_mode) or
            getattr(root_info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0)):
        return False
    with ExitStack() as stack:
        mapped={}
        parsed={}
        for name,item in plan['archives'].items():
            cancel()
            try:
                path=previous_assets/name
                info=path.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or
                        getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0) or
                        info.st_size!=item['before']['size']):
                    return False
                stream=stack.enter_context(path.open('rb'))
                raw=stack.enter_context(mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ))
            except OSError:
                return False
            if digest(raw,cancel)!=item['before']['sha256']:
                return False
            mapped[name]=raw
            parsed[name]=pck.read(raw)
        progress('Reusing verified characters, artwork and existing animations...')
        with ExitStack() as originals:
            streams={}
            for name,pin_value in metadata['originals'].items():
                character_content.checked_file(assets/name,pin_value,cancel)
                streams[name]=originals.enter_context((assets/name).open('rb'))
            source=character_content.Source(streams,metadata,cancel,progress)
            pack=mapped['packfile.pck']
            entries={e['name']:e for e in parsed['packfile.pck']['entries']}
            def previous(path):
                cancel()
                entry=entries[pck.canonical(path)]
                return pack[entry['offset']:entry['offset']+entry['size']]
            generated=body_resources(previous,source)
            wanted={row['name'] for item in plan['archives'].values() for row in item.get('resources',())
                    if row['source']=='generated'}
            if set(generated)!=wanted:
                raise ValueError('Character update generated resource set differs')
        with tempfile.TemporaryDirectory(prefix='.character-update-',dir=assets) as temporary:
            staged=Path(temporary)
            for name,item in plan['archives'].items():
                cancel()
                raw=mapped[name]
                old={e['name']:e for e in parsed[name]['entries']}
                progress('Writing updated character archive: '+name)
                with (staged/name).open('xb') as output:
                    def emit(data):
                        for at in range(0,len(data),CHUNK):
                            cancel()
                            output.write(data[at:at+CHUNK])
                    if item.get('reuse'):
                        for at in range(0,len(raw),CHUNK):
                            emit(raw[at:at+CHUNK])
                    else:
                        prefix=item['prefix']
                        position=prefix['size']
                        if digest(raw,cancel,0,position)!=prefix['sha256']:
                            raise ValueError('Character update prefix changed')
                        for at in range(0,position,CHUNK):
                            emit(raw[at:min(position,at+CHUNK)])
                        target={e['name']:e for e in item['index']['entries']}
                        for done,resource in enumerate(item['resources'],1):
                            cancel()
                            path=resource['name']
                            entry=target[path]
                            if resource['source']=='generated':
                                data=generated[path]
                            else:
                                prior=old[path]
                                data=raw[prior['offset']:prior['offset']+prior['size']]
                                if resource['source']=='preload':
                                    if pck.sha(data)!=resource['before_sha256']:
                                        raise ValueError('Character preload changed during update')
                                    suffix=[plan['dependencies'][i] for i in plan['suffixes'][resource['suffix']]]
                                    data=preload(data,resource['keep_rows'],suffix)
                            if len(data)!=resource['size'] or pck.sha(data)!=resource['sha256']:
                                raise ValueError('Character update resource verification failed: '+path)
                            emit(bytes(entry['offset']-position))
                            emit(data)
                            position=entry['offset']+len(data)
                            if done%100==0 or done==len(item['resources']):
                                progress(f'Writing updated animations: {done:,}/{len(item["resources"]):,} files in {name}')
                        emit(bytes(item['index']['start']-position))
                        emit(index_bytes(item,parsed[name]))
                character_content.checked_file(staged/name,item['after'],cancel)
            cancel()
            for name in plan['archives']:
                os.replace(staged/name,assets/name)
    return True
