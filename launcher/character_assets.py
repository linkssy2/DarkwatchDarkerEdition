"""Checked BXML and character presentation transforms for the user's own disc.

Only presentation fields change. Original actors, scripts, inventory and events
are retained; generated game assets are written only into the local installation.
"""
import copy
import struct

PLAYER = 'CassidyPlayerTwo'
HANDS = 'CassidyPlayerTwoHands'
MODEL = 'Characters/Cassidy/Base_Cassidy'
LOCATOR = 'Characters/Player_Two/CassidyPlayerTwo'
HANDS_MODEL = 'Characters/Player_First/Base_POV_CassidyPlayerTwo'
RAGDOLL = 'Characters/DWAgentFemale/BASE_DWagent_female_ragdoll'
HURT = {'DAMAGELIGHT':'CASS_DMG_L', 'DAMAGEMODERATE':'CASS_DMG_M', 'DAMAGESEVERE':'CASS_DMG_H'}
VOICE = dict(HURT, DEATH='CASS_DMG_H')
BODY_MAPS = {
    'Multi': ('Characters/MultiplayerCoOp/MultiplayerCoOpAnimation', 'Characters/Player_Two/CassidyCoopAnimation'),
    'NotMulti': ('Characters/Player_Third/ChazBasicAnimation', 'Characters/Player_Two/CassidyBasicAnimation'),
    'Horse': ('Characters/Player_Third/ChazHorseAnimation', 'Characters/Player_Two/CassidyHorseAnimation'),
    'Vehicle': ('Characters/Player_Third/ChazVehicleAnimation', 'Characters/Player_Two/CassidyVehicleAnimation'),
}
SOLO = 'CassidySolo'
SOLO_HANDS = 'CassidySoloHands'
SOLO_LOCATOR = 'Characters/Player_Two/CassidySolo'
SOLO_MULTI = 'Characters/Player_Two/CassidySoloMultiplayerAnimation'
JERICHO = 'JerichoCoop'
JERICHO_LOCATOR = 'Characters/Player_Two/JerichoCoop'
KINDS = ('BoneAnimatedResource', 'AnimatedPathResource', 'EventSequenceResource')


def decode(raw):
    """Read the bounded version-one ASCII/string-index resource format."""
    if raw[:4] != b'\x01\0\0\0':
        raise ValueError('Unsupported character XML version')
    pos, nodes = 4, 0
    def word():
        nonlocal pos
        if pos + 2 > len(raw):
            raise ValueError('Truncated character XML')
        value = struct.unpack_from('<H', raw, pos)[0]
        pos += 2
        return value
    count = word()
    if count >= 20000:
        raise ValueError('Character XML string limit')
    strings = []
    for _ in range(count):
        length = word()
        if length >= 4096 or pos + length > len(raw):
            raise ValueError('Invalid character XML string')
        strings.append(raw[pos:pos + length].decode('ascii'))
        pos += length
    def text(index):
        if index >= len(strings):
            raise ValueError('Invalid character XML string index')
        return strings[index]
    def node(depth=0):
        nonlocal nodes
        nodes += 1
        if nodes >= 300000 or depth >= 64:
            raise ValueError('Character XML nesting limit')
        name, count = text(word()), word()
        if count >= 64:
            raise ValueError('Character XML attribute limit')
        attrs = {}
        for _ in range(count):
            key, value = text(word()), text(word())
            if key in attrs:
                raise ValueError('Duplicate character XML attribute')
            attrs[key] = value
        count = word()
        if count >= 20000:
            raise ValueError('Character XML child limit')
        children = [node(depth + 1) for _ in range(count)]
        value = word()
        return dict(name=name, attributes=attrs, children=children,
                    value=None if value == 65535 else text(value))
    result = node()
    if pos != len(raw):
        raise ValueError('Trailing character XML data')
    return result


def walk(node):
    yield node
    for child in node['children']:
        yield from walk(child)


def encode(tree):
    """Serialize the witnessed version-one ASCII/string-index BXML schema."""
    strings, indexes = [], {}
    def word(n):
        if not 0 <= n < 65536:
            raise ValueError('BXML word out of range')
        return struct.pack('<H', n)
    def text(s):
        if not isinstance(s, str) or len(s.encode('ascii')) >= 4096:
            raise ValueError('Invalid BXML string')
        if s not in indexes:
            if len(strings) >= 19999:
                raise ValueError('Too many BXML strings')
            indexes[s] = len(strings)
            strings.append(s.encode('ascii'))
        return word(indexes[s])
    nodes = 0
    def node(n, depth=0):
        nonlocal nodes
        nodes += 1
        if depth >= 64 or nodes >= 300000 or len(n['attributes']) >= 64 or len(n['children']) >= 20000:
            raise ValueError('BXML structure exceeds witnessed bounds')
        raw = text(n['name']) + word(len(n['attributes']))
        raw += b''.join(text(k)+text(v) for k,v in n['attributes'].items())
        raw += word(len(n['children'])) + b''.join(node(c,depth+1) for c in n['children'])
        return raw + (word(65535) if n['value'] is None else text(n['value']))
    body = node(tree)
    return b'\x01\0\0\0' + word(len(strings)) + b''.join(word(len(s))+s for s in strings) + body


def child(parent, name):
    matches = [c for c in parent['children'] if c['attributes'].get('name') == name]
    if len(matches) != 1:
        raise ValueError(f'Expected one {name}')
    return matches[0]


def norm(value):
    return value.replace('\\','/').lower()


def named(parent, name):
    matches = [n for n in parent['children'] if n['name'] == name]
    if len(matches) != 1:
        raise ValueError(f'Expected one {name} node')
    return matches[0]


def fields(row):
    if row['name'] != 'element' or row['attributes'] or row['value'] is not None:
        raise ValueError('Unexpected list element')
    result = {n['name']:n['value'] for n in row['children']}
    if len(result) != len(row['children']) or any(n['children'] or n['attributes'] for n in row['children']):
        raise ValueError('Unexpected list field')
    return result


def element(values):
    return dict(name='element',attributes={},value=None,children=[
        dict(name=k,attributes={},value=v,children=[]) for k,v in values.items()])


def remove_coop_eye_billboards(player):
    # The stock co-op body uses two eye billboards absent from Chaz and Cassidy.
    eye = child(player,'BillboardSpriteRenderComponent')
    mapping = child(eye,'m_locatorToBillboardMap')['children']
    if (len(eye['children']) != 2 or [n['attributes'] for n in mapping] != [
            dict(key=key,value='FX/Billboards/eyeGlow_billboards') for key in ('loc_LeftEye','loc_RightEye')]
            or child(eye,'m_visibleIn')['attributes']['value'] != 'ThirdPersonOnly'):
        raise ValueError('Unrecognized billboard behavior; refusing to remove it')
    player['children'].remove(eye)


def candidate(original, cues, repainted_hands=False):
    if not set(HURT.values()).issubset(cues):
        raise ValueError('Cassidy hurt audio is absent')
    if any(c['attributes'].get('name') in (PLAYER,HANDS) for c in original['children']):
        raise ValueError('Candidate already contains player-two actors')
    player = copy.deepcopy(child(original,'CoOpChaz'))
    hands = copy.deepcopy(child(original,'ChazHands'))
    player['attributes']['name'], hands['attributes']['name'] = PLAYER, HANDS
    remove_coop_eye_billboards(player)
    animation = child(player,'AnimationComponent')
    animation_map = child(animation,'m_AnimationFiles')['children']
    for alias,(source,target) in BODY_MAPS.items():
        rows = [n for n in animation_map if n['attributes'].get('key') == alias]
        if len(rows) != 1 or norm(rows[0]['attributes']['value']) != norm(source):
            raise ValueError('Unexpected player animation alias')
        rows[0]['attributes']['value'] = target
    npc_ragdoll = child(child(child(original,'AgentCassidy'),'AnimationComponent'),'m_ragdollFileName')
    if npc_ragdoll['attributes']['value'] != RAGDOLL:
        raise ValueError('Cassidy NPC ragdoll reference differs')
    child(animation,'m_ragdollFileName')['attributes']['value'] = RAGDOLL
    if repainted_hands:
        hp = child(hands,'PlayerHandsComponent')
        child(hp,'m_HandsModel')['attributes']['value'] = HANDS_MODEL
        variants = child(hp,'m_AlternativeHandsModels')['children']
        if len(variants) != 5 or any(n['name'] != 'string' for n in variants):
            raise ValueError('Unexpected first-person hand variants')
        for n in variants:
            n['attributes']['value'] = HANDS_MODEL
        child(child(hands,'LocatorAttachmentComponent'),'m_locatorFileName')['attributes']['value'] = HANDS_MODEL
    render = child(player,'AlternativeModelsRenderComponent')
    child(render,'m_modelResourcePath')['attributes']['value'] = MODEL
    variants = child(render,'m_alternativeModelPaths')['children']
    if len(variants) != 4 or any(n['name'] != 'string' for n in variants):
        raise ValueError('Unexpected player body variants')
    for n in variants:
        n['attributes']['value'] = MODEL
    child(child(player,'InventoryComponent'),'m_handActorName')['attributes']['value'] = HANDS
    child(child(player,'LocatorAttachmentComponent'),'m_locatorFileName')['attributes']['value'] = LOCATOR
    speaker = child(child(player,'SpeakerComponent'),'m_speakerMap')
    for event,cue in VOICE.items():
        rows = [n for n in speaker['children'] if n['attributes'].get('key') == event]
        if len(rows) != 1 or rows[0]['attributes']['bank'] != 'VOICE':
            raise ValueError('Unexpected player hurt mapping')
        rows[0]['attributes'].update(bank='CASSIDY',sound=cue)
    # No established player voice hook for attack/jump/land/breath; surface effects stay intact.
    result = copy.deepcopy(original)
    result['children'].extend([player,hands])
    return result


def adapt_locators(player, npc):
    if player['name'] != 'locator_list' or npc['name'] != 'locator_list':
        raise ValueError('Unexpected locator schema')
    copied = {'loc_Head','loc_RightHand','loc_LeftHand'}
    if len(player['children']) != 15 or {n['attributes'].get('name') for n in npc['children']} != copied:
        raise ValueError('Unsupported player/Cassidy locator count')
    result = copy.deepcopy(player)
    for index,n in enumerate(result['children']):
        if n['attributes']['name'] in copied:
            result['children'][index] = copy.deepcopy(child(npc,n['attributes']['name']))
    if len({n['attributes']['name'] for n in result['children']}) != 15:
        raise ValueError('Duplicate player locator identity')
    return result


def append_resources(original, dependencies):
    if original['name'] != 'ResourceSetCInfo':
        raise ValueError('Unsupported resource-list root')
    result = copy.deepcopy(original)
    rows = named(result,'data')['children']
    keys = [(norm(fields(n)['name']),fields(n)['type']) for n in rows]
    if len(set(keys)) != len(keys) or any(set(fields(n)) != {'name','type'} for n in rows):
        raise ValueError('Resource-list duplicates or unexpected schema')
    seen = set(keys)
    added = []
    for name,kind in dependencies:
        key = norm(name),kind
        if key not in seen:
            rows.append(element(dict(name=name,type=kind)))
            seen.add(key)
            added.append(dict(name=name,type=kind))
    return result,added


def append_voice_bank(original):
    # Audio has a separate BankLayoutConfig, not a generic resource-list loader.
    if original['name'] != 'BankLayoutConfig' or named(original,'layoutType')['value'] != 'HubCoop':
        raise ValueError('Unsupported co-op bank-layout schema')
    result = copy.deepcopy(original)
    rows = named(result,'banks')['children']
    names = [fields(n)['name'].upper() for n in rows]
    # Original files contain unrelated duplicate aliases; preserve their routing/order.
    if names.count('CASSIDY') > 1:
        raise ValueError('Duplicate original Cassidy bank alias')
    if 'CASSIDY' in names:
        if fields(rows[names.index('CASSIDY')]) != {'name':'CASSIDY','file':'CASSIDY'}:
            raise ValueError('Unexpected existing Cassidy bank routing')
        return result,False
    rows.append(element(dict(name='CASSIDY',file='CASSIDY')))
    return result,True


def dependencies(repainted_hands=False):
    models = [HANDS_MODEL] if repainted_hands else [
        'Characters/Player_First/BASE_POV_'+m for m in ('CHAZ','BLUE','RED','civchaz')]
    result = [(MODEL,'ModelResource'),(MODEL,'SkeletonLayoutResource'),(LOCATOR,'LocatorResource'),(RAGDOLL,'HavokObjectResource'),
              ('Characters/Player_First/ChazHands','AnimatedCharacterResource'),
              (HANDS_MODEL if repainted_hands else 'Characters/Player_First/BASE_POV_Chaz','LocatorResource')]
    return result + [(m,t) for m in models for t in ('ModelResource','SkeletonLayoutResource')]


def solo_actor(original):
    """Alter only presentation fields; retain the native solo component schema."""
    result=copy.deepcopy(child(original,'Chaz'))
    result['attributes']['name']=SOLO
    render=child(result,'AlternativeModelsRenderComponent')
    if norm(child(render,'m_modelResourcePath')['attributes']['value'])!='characters/player_third/base_chaz':
        raise ValueError('Unexpected native solo body')
    child(render,'m_modelResourcePath')['attributes']['value']=MODEL
    variants=child(render,'m_alternativeModelPaths')['children']
    if len(variants)!=5 or any(n['name']!='string' for n in variants):raise ValueError('Unexpected solo variants')
    for row in variants:row['attributes']['value']=MODEL
    child(child(result,'InventoryComponent'),'m_handActorName')['attributes']['value']=SOLO_HANDS
    child(child(result,'LocatorAttachmentComponent'),'m_locatorFileName')['attributes']['value']=SOLO_LOCATOR
    animation=child(result,'AnimationComponent')
    rows=child(animation,'m_AnimationFiles')['children']
    if len(rows)!=4:raise ValueError('Unexpected solo animation maps')
    for row in rows:
        key=row['attributes']['key']
        source,target=BODY_MAPS[key]
        if key=='Multi':source,target='Characters/Multiplayer/MultiplayerAnimation',SOLO_MULTI
        if norm(row['attributes']['value'])!=norm(source):raise ValueError('Unexpected solo animation source')
        row['attributes']['value']=target
    child(animation,'m_ragdollFileName')['attributes']['value']=RAGDOLL
    voice=child(child(result,'SpeakerComponent'),'m_speakerMap')['children']
    for event,cue in VOICE.items():
        rows=[r for r in voice if r['attributes']['key']==event]
        if len(rows)!=1 or rows[0]['attributes']['bank']!='VOICE':raise ValueError('Unexpected solo voice event')
        rows[0]['attributes'].update(bank='CASSIDY',sound=cue)
    return result


def solo_locators(original,npc):
    if original['name']!='locator_list' or len(original['children'])!=13:raise ValueError('Unexpected solo locators')
    copied={'loc_Head','loc_RightHand','loc_LeftHand'}
    if {n['attributes']['name'] for n in npc['children']}!=copied:raise ValueError('Unexpected Cassidy locators')
    result=copy.deepcopy(original)
    for i,node in enumerate(result['children']):
        if node['attributes']['name'] in copied:
            result['children'][i]=copy.deepcopy(child(npc,node['attributes']['name']))
    return result


def solo_bank(original):
    if original['name']!='BankLayoutConfig' or named(original,'layoutType')['value']!='Hub':
        raise ValueError('Unexpected solo bank layout')
    result=copy.deepcopy(original)
    rows=named(result,'banks')['children']
    names=[fields(row) for row in rows]
    found=[row for row in names if row['name'].upper()=='CASSIDY']
    if found:
        if len(found)!=1 or found[0]!={'name':'CASSIDY','file':'CASSIDY'}:raise ValueError('Unsupported existing Cassidy bank')
        return result,False
    rows.append(element(dict(name='CASSIDY',file='CASSIDY')))
    return result,True


def mode_dependencies(tables,solo,solo_clips):
    """Only preload the private maps used by this native actor family."""
    deps=dependencies(True)
    if solo:
        deps=[(SOLO_LOCATOR if norm(name)==norm(LOCATOR) else name,kind)
              for name,kind in deps]
    tables=[table for table in tables if not solo or table['alias']!='Multi']
    for table in tables:
        deps.append((table['output'][:-5],'AnimatedCharacterResource'))
        deps.extend((clip['output'][:-5],kind) for clip in table['clips'] for kind in KINDS)
    if solo:
        deps.append((SOLO_MULTI,'AnimatedCharacterResource'))
        deps.extend((clip['output'][:-5],kind) for clip in solo_clips for kind in KINDS)
    # Shared aliases can name the same converted clip. Keep one preload/type pair.
    unique={}
    for name,kind in deps:unique.setdefault((norm(name),kind),(name,kind))
    return list(unique.values())


def jericho_actor(original):
    result = copy.deepcopy(child(original, 'CoOpChaz'))
    source = child(original, 'Chaz')
    remove_coop_eye_billboards(result)
    result['attributes']['name'] = JERICHO
    render = child(result, 'AlternativeModelsRenderComponent')
    body = child(child(source, 'AlternativeModelsRenderComponent'), 'm_modelResourcePath')['attributes']['value']
    child(render, 'm_modelResourcePath')['attributes']['value'] = body
    variants = child(render, 'm_alternativeModelPaths')['children']
    if len(variants) != 4:
        raise ValueError('Unexpected native co-op body alternatives')
    for row in variants:
        row['attributes']['value'] = body
    animation, original_animation = child(result, 'AnimationComponent'), child(source, 'AnimationComponent')
    sources = {row['attributes']['key']: row['attributes']['value']
               for row in child(original_animation, 'm_AnimationFiles')['children']}
    if set(sources) != {'Multi', 'NotMulti', 'Horse', 'Vehicle'}:
        raise ValueError('Unexpected Chaz animation map family')
    for row in child(animation, 'm_AnimationFiles')['children']:
        row['attributes']['value'] = sources[row['attributes']['key']]
    child(animation, 'm_ragdollFileName')['attributes']['value'] = child(original_animation, 'm_ragdollFileName')['attributes']['value']
    child(child(result, 'LocatorAttachmentComponent'), 'm_locatorFileName')['attributes']['value'] = JERICHO_LOCATOR
    return result


def jericho_locators(chaz, coop, joints):
    chaz_by_name = {row['attributes']['name']: row for row in chaz['children']}
    extras = {row['attributes']['name'] for row in coop['children']} - chaz_by_name.keys()
    if len(chaz_by_name) != 13 or len(coop['children']) != 15 or extras != {'loc_RightWeapon', 'loc_HeadAccessory', 'loc_NeckGore'}:
        raise ValueError('Unexpected Chaz/co-op locator identities')
    result = copy.deepcopy(coop)
    for i, row in enumerate(result['children']):
        name = row['attributes']['name']
        if name in chaz_by_name:
            result['children'][i] = copy.deepcopy(chaz_by_name[name])
    if any(row['attributes']['parent'] not in joints | {'ORIGIN'} for row in result['children']):
        raise ValueError('Co-op locator parent is absent from Chaz skeleton')
    return result
