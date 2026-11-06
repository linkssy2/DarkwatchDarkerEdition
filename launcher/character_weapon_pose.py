"""Preserve rifle-family hand contacts while adapting authored body poses.

Generated visual clones retain original action/event/translation data. Independent
aim overlays use their corrected stance reference; no gameplay action is replaced.
"""
import bisect
import copy
import hashlib
import math
from pathlib import Path
import re
import struct
try:
    from . import character_animation as a, character_boss as b, character_assets as art
except ImportError:
    import character_animation as a
    import character_boss as b
    import character_assets as art

ARMS=(12,13,14,15,18,19,20)
MISSING=0xffffffff


def add(x,y):return tuple(u+v for u,v in zip(x,y))
def sub(x,y):return tuple(u-v for u,v in zip(x,y))
def scale(x,s):return tuple(u*s for u in x)
def dot(x,y):return sum(u*v for u,v in zip(x,y))
def length(x):return math.sqrt(dot(x,x))
def unit(x):
    size=length(x)
    if size<1e-10:raise ValueError('Degenerate arm direction')
    return scale(x,1/size)
def cross(x,y):return (x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0])
def rotate(v,m):return tuple(sum(v[j]*m[j][i]for j in range(3))for i in range(3))
def mul(x,y):return a._multiply(x[0],y[0]),add(rotate(x[1],y[0]),y[1])
def inverse(x):
    rotation=a._inverse(x[0]);return rotation,scale(rotate(x[1],rotation),-1)


def align(x,y):
    x,y=unit(x),unit(y);v=cross(x,y);sine=length(v);cosine=max(-1.,min(1.,dot(x,y)))
    if sine<1e-10:
        if cosine<0:raise ValueError('Ambiguous half-turn arm direction')
        return a.IDENTITY
    x,y,z=scale(v,1/sine);k=((0.,-z,y),(z,0.,-x),(-y,x,0.));square=a._multiply(k,k)
    return a._transpose(tuple(tuple(a.IDENTITY[i][j]+k[i][j]*sine+square[i][j]*(1-cosine)
                                   for j in range(3))for i in range(3)))


def world(local,parents):
    result={}
    def resolve(bone):
        if bone not in result:
            parent=parents[bone];result[bone]=local[bone]if parent is None else mul(local[bone],resolve(parent))
        return result[bone]
    for bone in local:resolve(bone)
    return result


def localize(pose,parents):
    return {bone:pose[bone]if parent is None else mul(pose[bone],inverse(pose[parent]))
            for bone,parent in parents.items()}


def rig(model,bones):
    rows,_,_=b.rig(model,bones)
    return ({bone:(tuple(tuple(row['rotation'][i:i+3])for i in(0,3,6)),tuple(row['translation']))
             for bone,row in rows.items()}, {bone:row['parent_bone']for bone,row in rows.items()})


class Clip:
    def __init__(self,data,bones,allow_additive=False):
        self.data=data;self.flags,self.parts=b.sections(data,bones);self.tracks={}
        if self.flags&0x10000000 and not allow_additive:raise ValueError('Support solver requires an absolute body pose')
        for bit in(4,32,8):
            section=self.parts.get(bit)
            if section is None:continue
            for bone,first in enumerate(section['indices']):
                if first==MISSING:continue
                stop=min([x for x in section['indices']if first<x<MISSING]+[section['count']])
                keys=[]
                for i in range(first,stop):
                    at=section['keys']+i*section['stride'];time=struct.unpack_from('<f',data,at)[0]
                    if bit==4:values=tuple(x/32768 for x in struct.unpack_from('<4h',data,at+4))
                    elif bit==32:values=a.decode_word(struct.unpack_from('<I',data,at+4)[0])
                    else:values=struct.unpack_from('<3f',data,at+4)
                    keys.append((time,values))
                self.tracks[(bone,8 if bit==8 else 4)]=([x[0]for x in keys],[x[1]for x in keys])

    def pose(self,bind,phase):
        result=dict(bind)
        for (bone,bit),(times,values)in self.tracks.items():
            index=bisect.bisect_left(times,phase)
            if index==0:value=values[0]
            elif index>=len(times):value=values[-1]
            else:
                lo,hi=values[index-1],values[index]
                if bit==4 and dot(lo,hi)<0:hi=scale(hi,-1)
                fraction=(phase-times[index-1])/(times[index]-times[index-1])
                value=add(scale(lo,1-fraction),scale(hi,fraction))
            rotation,position=result[bone]
            if bit==4:rotation=a._quaternion_matrix(unit(value))
            else:position=value
            result[bone]=rotation,position
        return result


def solve(shoulder,elbow,wrist,target):
    upper,fore=sub(elbow,shoulder),sub(wrist,elbow);l1,l2=length(upper),length(fore)
    original_axis=unit(sub(wrist,shoulder));axis=unit(sub(target,shoulder))
    pole=rotate(unit(sub(upper,scale(original_axis,dot(upper,original_axis)))),align(original_axis,axis))
    distance=min(l1+l2-1e-7,max(abs(l1-l2)+1e-7,length(sub(target,shoulder))))
    cosine=(distance*distance+l1*l1-l2*l2)/(2*distance*l1)
    middle=add(shoulder,add(scale(axis,l1*cosine),scale(pole,l1*math.sqrt(max(0.,1-cosine*cosine)))))
    endpoint=add(shoulder,scale(axis,distance))
    if length(sub(endpoint,target))>1e-5:raise ValueError('Arm target is unreachable')
    return middle,endpoint


class SupportRetarget:
    arm_bones=ARMS
    def __init__(self,source_model,target_model,source_grip,target_grip,target_bones=22):
        self.source,self.source_parents=rig(source_model,22)
        self.target,self.parents=rig(target_model,target_bones)
        self.bones=target_bones;self.source_grip=source_grip;self.target_grip=target_grip
        old,new=world(self.source,self.source_parents),world(self.target,self.parents)
        self.maps={bone:a._multiply(new[bone][0],a._inverse(old[bone][0]))for bone in range(22)}

    def sample(self,source,target,phase,right_offset=0.,new_grip_offset=None):
        native=source.pose(self.source,phase);before_local=target.pose(self.target,phase)
        return self.correct(native,before_local,right_offset,new_grip_offset)

    def correct(self,native,before_local,right_offset=0.,new_grip_offset=None):
        before=world(before_local,self.parents);local=dict(before_local);maps=dict(self.maps)
        maps[15]=a._multiply(a._multiply(a._inverse(local[16][0]),a._inverse(self.target_grip[0])),
                             a._multiply(self.source_grip[0],native[16][0]))
        for bone in(12,13,14,15):
            mapped=a._multiply(a._multiply(maps[bone],native[bone][0]),a._inverse(maps[self.source_parents[bone]]))
            local[bone]=mapped,local[bone][1]
        after=world(local,self.parents)
        old_locator=self.target_grip[0],add(self.target_grip[1],scale(self.target_grip[0][0],right_offset))
        target_offset=right_offset if new_grip_offset is None else new_grip_offset
        locator=self.target_grip[0],add(self.target_grip[1],scale(self.target_grip[0][0],target_offset))
        prior_gun=mul(old_locator,before[16]);current_gun=mul(locator,after[16])
        desired=mul(mul(before[20],inverse(prior_gun)),current_gun)
        return self.fit_contacts(before,after,desired)

    def fit_contacts(self,before,after,desired,*,reach_fraction=None):
        """Fit an explicit left-hand target while retaining both hand contacts."""
        after=dict(after)
        rs,re,rw=(after[x][1]for x in(13,14,15));ls,le,lw=(before[x][1]for x in(18,19,20))
        centers=(sub(rs,rw),sub(ls,desired[1]))
        radii=tuple(length(sub(before[w][1],before[s][1]))for s,w in((13,15),(18,20)))
        if reach_fraction is not None:
            if not math.isfinite(reach_fraction) or not 0 < reach_fraction < 1:
                raise ValueError('Invalid arm reach fraction')
            radii=tuple(reach_fraction*(length(sub(before[e][1],before[s][1]))+
                                        length(sub(before[w][1],before[e][1])))
                        for s,e,w in((13,14,15),(18,19,20)))
        gap=max(0.,length(sub(centers[0],centers[1]))-sum(radii));radii=tuple(r+gap*.5+1e-7 for r in radii)
        displacement=(0.,0.,0.);corrections=[displacement,displacement]
        for _ in range(500):
            previous=displacement
            for i in(0,1):
                trial=add(displacement,corrections[i]);offset=sub(trial,centers[i]);size=length(offset)
                projected=trial if size<=radii[i]else add(centers[i],scale(offset,radii[i]/size))
                corrections[i]=sub(trial,projected);displacement=projected
            if length(sub(previous,displacement))<1e-9:break
        middle,endpoint=solve(rs,re,rw,add(rw,displacement))
        weapon_relative=mul(after[16],inverse(after[15]))
        after[13]=a._multiply(after[13][0],align(sub(re,rs),sub(middle,rs))),after[13][1]
        after[14]=a._multiply(after[14][0],align(sub(rw,re),sub(endpoint,middle))),middle
        after[15]=after[15][0],endpoint;after[16]=mul(weapon_relative,after[15])
        middle,endpoint=solve(ls,le,lw,add(desired[1],displacement))
        after[18]=a._multiply(before[18][0],align(sub(le,ls),sub(middle,ls))),ls
        after[19]=a._multiply(before[19][0],align(sub(lw,le),sub(endpoint,middle))),middle
        after[20]=desired[0],endpoint
        after[21]=mul(mul(before[21],inverse(before[20])),after[20])
        return localize(after,self.parents)

    def bake(self,source,adapted,right_offset=0.,synchronize=True,new_grip_offset=None):
        native=Clip(source,22);target=Clip(adapted,self.bones)
        phases={0.,1.}
        for clip in(native,target):
            for times,_ in clip.tracks.values():phases.update(times)
        cache={}
        def sample(phase):
            if phase not in cache:cache[phase]=self.sample(native,target,phase,right_offset,new_grip_offset)
            return cache[phase]
        return self._encode_rotations(target,sample,phases,synchronize),len(cache)

    def _encode_rotations(self,target,sample,phases,synchronize=True):
        adapted=target.data;section=target.parts.get(4)
        if section is None or 32 in target.parts:raise ValueError('Prepared rotations must be expanded')
        keys=bytearray();indices=[]
        for bone,first in enumerate(section['indices']):
            if first==MISSING:indices.append(first);continue
            indices.append(len(keys)//12)
            stop=min([x for x in section['indices']if first<x<MISSING]+[section['count']])
            if bone not in self.arm_bones:
                keys+=adapted[section['keys']+12*first:section['keys']+12*stop];continue
            times=sorted(phases)if synchronize else target.tracks[(bone,4)][0]
            previous=None
            for phase in times:
                q=a._to_quaternion(sample(phase)[bone][0])
                if previous is not None and dot(q,previous)<0:q=scale(q,-1)
                previous=q
                keys+=struct.pack('<f4h',phase,*[max(-32768,min(32767,round(x*32768)))for x in q])
        block=struct.pack('<I',len(keys)//12)+struct.pack('<'+'I'*self.bones,*indices)+keys
        output=adapted[:section['start']]+block+adapted[section['end']:]
        _,parts=b.sections(output,self.bones)
        if output[:24]!=adapted[:24]:raise ValueError('Body action header changed')
        for bit,old in target.parts.items():
            if bit==4:continue
            new=parts[bit]
            if adapted[old['start']:old['end']]!=output[new['start']:new['end']]:
                raise ValueError('Non-rotation animation data changed')
        return output

    def shift_grip(self,before_local,new_offset,old_offset=0.):
        """Move the support grip with an attachment shift, without re-aiming."""
        if new_offset==old_offset:return dict(before_local)
        before=world(before_local,self.parents)
        def gun(offset):
            locator=self.target_grip[0],add(self.target_grip[1],scale(self.target_grip[0][0],offset))
            return mul(locator,before[16])
        desired=mul(mul(before[20],inverse(gun(old_offset))),gun(new_offset))
        return self.fit_contacts(before,before,desired)

    def bake_grip(self,adapted,new_offset,old_offset=0.):
        if new_offset==old_offset:return adapted
        target=Clip(adapted,self.bones);phases={0.,1.};cache={}
        for times,_ in target.tracks.values():phases.update(times)
        def sample(phase):
            if phase not in cache:cache[phase]=self.shift_grip(target.pose(self.target,phase),new_offset,old_offset)
            return cache[phase]
        return self._encode_rotations(target,sample,phases)

    def bake_grip_delta(self,adapted_base,adapted_delta,new_offset,old_offset=0.):
        if new_offset==old_offset:return adapted_delta
        base=Clip(adapted_base,self.bones).pose(self.target,.5)
        target=Clip(adapted_delta,self.bones,True)
        if not target.flags&0x10000000:raise ValueError('Expected additive support pose')
        corrected=self.shift_grip(base,new_offset,old_offset);cache={}
        identity={bone:(a.IDENTITY,(0.,0.,0.))for bone in base}
        def sample(phase):
            if phase not in cache:
                delta=target.pose(identity,phase)
                combined={bone:(a._multiply(value[0],delta[bone][0]),add(value[1],delta[bone][1]))
                          for bone,value in base.items()}
                desired=self.shift_grip(combined,new_offset,old_offset)
                cache[phase]={bone:(a._multiply(a._inverse(corrected[bone][0]),desired[bone][0]),delta[bone][1])
                              for bone in base}
            return cache[phase]
        phases={0.,1.}
        for times,_ in target.tracks.values():phases.update(times)
        return self._encode_rotations(target,sample,phases)

    def bake_delta(self,source_base,adapted_base,source_delta,adapted_delta,*,right_offset=0.,new_grip_offset=None):
        native_base=Clip(source_base,22);target_base=Clip(adapted_base,self.bones)
        native_delta=Clip(source_delta,22,True);target_delta=Clip(adapted_delta,self.bones,True)
        if not(native_delta.flags&target_delta.flags&0x10000000):raise ValueError('Expected additive aim poses')
        original=native_base.pose(self.source,.5);before=target_base.pose(self.target,.5)
        corrected=self.correct(original,before,right_offset,new_grip_offset);cache={};output=bytearray(adapted_delta)
        def combined(base,delta,phase):
            identity={bone:(a.IDENTITY,(0.,0.,0.))for bone in base}
            pose=delta.pose(identity,phase)
            return {bone:(a._multiply(value[0],pose[bone][0]),add(value[1],pose[bone][1]))
                    for bone,value in base.items()}
        part=target_delta.parts[4]
        for bone in self.arm_bones:
            first=part['indices'][bone]
            if first==MISSING:continue
            stop=min([x for x in part['indices']if first<x<MISSING]+[part['count']])
            for i in range(first,stop):
                at=part['keys']+12*i;phase=struct.unpack_from('<f',adapted_delta,at)[0]
                if phase not in cache:
                    cache[phase]=self.correct(combined(original,native_delta,phase),combined(before,target_delta,phase),
                                              right_offset,new_grip_offset)
                rotation=a._multiply(a._inverse(corrected[bone][0]),cache[phase][bone][0])
                q=a._to_quaternion(rotation)
                struct.pack_into('<4h',output,at+4,*[max(-32768,min(32767,round(x*32768)))for x in q])
        return bytes(output)


FAMILIES={'RIFLE','SNIPERRIFLE','CROSSBOW'}
WEAPONS=FAMILIES|{'PISTOL','REVOLVER','DOUBLEPISTOL','SHOTGUN','RAILRCKT'}
GROUPS={'Alert Poses UB','Crouch Alert Poses','Movement UB Rifle','Crouch Movement Rifle',
        'Rifle Aim','Reload Rifle','Reload Sniper Rifle','Reload Crossbow'}
PREFIX='characters/player_two/weaponpose/'
GRIP_PREFIX='characters/player_two/weapongrip/'

GRIP_ACTORS={'Chaz','JerichoCoop','CassidySolo','CassidyPlayerTwo','CassidySpectralSolo',
             'CassidySpectralPlayerTwo','CivilianJerichoSolo','CivilianJerichoCoop','TrooperSolo',
             'TrooperCoop','BlueTrooperSolo','BlueTrooperCoop','RedTrooperSolo','RedTrooperCoop',
             'TalaSolo','TalaCoop','VampireTalaSolo','VampireTalaCoop','BossTalaSolo','BossTalaCoop'}
GRIP_WEAPONS={'BasicPistol','Revolver','DoublePistol','Rifle','Shotgun','SniperRifle','Crossbow','RocketLauncher'}


def read_grip_offsets(raw=None):
    """Read the same finite, bounded attachment values compiled into the game."""
    if raw is None:raw=Path(__file__).with_name('body_weapon_grips.inc').read_text(encoding='utf-8')
    rows={}
    for line in raw.splitlines():
        line=line.split('//',1)[0].strip()
        if not line:continue
        match=re.fullmatch(r'BODY_WEAPON_GRIP\("([A-Za-z0-9]+)",\s*"([A-Za-z0-9]+)",\s*([0-9.]+),\s*([0-9.]+)\)',line)
        if match is None:raise ValueError('Malformed body weapon grip row')
        actor,weapon,right,left=match.groups()
        if actor not in GRIP_ACTORS or weapon not in GRIP_WEAPONS:raise ValueError('Unknown body weapon grip binding')
        key=actor,weapon
        if key in rows:raise ValueError('Duplicate body weapon grip binding')
        values=tuple(float(value)for value in(right,left))
        if not all(math.isfinite(value)and 0.<=value<=.08 for value in values):
            raise ValueError('Body weapon grip offset is outside the supported range')
        if weapon!='DoublePistol'and values[1]!=0.:raise ValueError('Unexpected left weapon attachment')
        rows[key]=values
    return rows


def _grip(raw):
    rows=[row['attributes']for row in art.decode(raw)['children']if row['attributes'].get('name')=='loc_RightHand']
    if len(rows)!=1 or rows[0].get('parent')!='weaponJoint_RightHand':
        raise ValueError('Unexpected right-hand weapon locator')
    q=tuple(float(x)for x in rows[0]['rot'].split(','));p=tuple(float(x)for x in rows[0]['pos'].split(','))
    if len(q)!=4 or len(p)!=3 or not all(math.isfinite(x)for x in q+p)or abs(dot(q,q)-1)>1e-5:
        raise ValueError('Invalid weapon locator transform')
    return a._quaternion_matrix(q),p


def _original(path):
    path=art.norm(path)
    return path[path.rfind('/characters/')+1:]if'/characters/'in path else path


def prepare_grip_table(raw,read,read_original,target_model,target_locator,basis,actor,offsets=None):
    """Fit support grips and the Redeemer's separate two-handed fan pose."""
    if actor not in GRIP_ACTORS:raise ValueError('Unknown body grip actor')
    offsets=read_grip_offsets()if offsets is None else offsets
    selected={weapon:value[0]for (name,weapon),value in offsets.items()
              if name==actor and weapon not in('BasicPistol','DoublePistol','Shotgun')and value[0]}
    if not selected.keys()<={'Revolver','Rifle','SniperRifle'}:
        raise ValueError('Unverified supporting-weapon grip family')
    if basis not in(a.CHAZ,a.STORM):raise ValueError('Unknown body animation source basis')
    frames=next((start,end)for tag,start,end,_ in b._records(target_model)if tag==14)
    _,start,_=next(a._chunks(target_model,*frames));bones=struct.unpack_from('<I',target_model,start)[0]-1
    if bones not in(22,51):raise ValueError('Unknown player body hierarchy')
    source_locator=read_original(basis[:-4]+('_coop.bllist'if basis==a.STORM else'.bllist'))
    solver=SupportRetarget(read_original(basis),target_model,_grip(source_locator),_grip(target_locator),bones)
    wrist=a._multiply(a._multiply(a._inverse(solver.target[16][0]),a._inverse(solver.target_grip[0])),
                       a._multiply(solver.source_grip[0],solver.source[16][0]))
    fan_basis=not all(abs(matrix[i][j]-a.IDENTITY[i][j])<1e-10
        for matrix in(*solver.maps.values(),wrist)for i in range(3)for j in range(3))
    if fan_basis:selected.setdefault('Revolver',0.)
    if not selected:return raw,{}
    tree=art.decode(raw)
    if tree['name']!='AnimationSystem':raise ValueError('Expected body animation system')
    references={};rows=[]
    for group in tree['children']:
        if group['name']!='AnimationGroup':continue
        name=group['attributes'].get('ToolName','')
        for node in group['children']:
            if node['name']!='KeyframeAnimation':continue
            flags={child['attributes']['Flag']for child in node['children']if child['name']=='Modifier'}
            path=art.norm(node['attributes']['Name'])+'.sanm'
            for weapon in selected:
                flag=weapon.upper()
                if flag not in flags:continue
                stance='CROUCH'if'CROUCH'in flags else'STAND'
                if name in('Alert Poses UB','Crouch Alert Poses'):references[weapon,stance]=path
                if weapon=='Revolver':
                    fan=name=='Weapon Shoot'and node['attributes'].get('AnimationID')=='ALT_SHOOT'
                    if fan:references[weapon,'FAN']=path
                    if not(fan or name=='Reload Pistol'and selected[weapon]or name=='Pistol Aim'and'hammerfan'in path):continue
                    if name=='Pistol Aim':stance='FAN'
                elif not(name in('Alert Poses UB','Crouch Alert Poses','Weapon Shoot')or
                         name.startswith(('Movement UB ','Crouch Movement ','Reload '))or name.endswith(' Aim')):
                    continue
                rows.append((group,node,flags,path,weapon,stance))
    additions={};replacements={};by_node={}
    for group,node,flags,path,weapon,stance in rows:
        data=read(path);additive=bool(struct.unpack_from('<I',data,20)[0]&0x10000000)
        reference=references.get((weapon,stance))if additive else None
        if additive and reference is None:raise ValueError('Missing support-grip stance reference')
        offset=selected[weapon];key=path,offset,reference
        if key not in replacements:
            data=(solver.bake_grip_delta(read(reference),data,offset)if additive else solver.bake_grip(data,offset))
            # Fan clips bypass the ordinary one-handed arm retarget. Preserve
            # their measured support contact while correcting that missing basis.
            if fan_basis and weapon=='Revolver'and group['attributes']['ToolName']!='Reload Pistol':
                source=read_original(_original(path))
                if additive:
                    gripped_base=solver.bake_grip(read(reference),offset)
                    data=solver.bake_delta(read_original(_original(reference)),gripped_base,source,data,right_offset=offset)
                else:data,_=solver.bake(source,data,right_offset=offset)
            name=GRIP_PREFIX+hashlib.sha256(data).hexdigest()[:24]
            replacements[key]=name;additions[name+'.sanm']=data
        replacement=copy.deepcopy(node);replacement['attributes']['Name']=replacements[key]
        replacement['children']=[child for child in replacement['children']if not(child['name']=='Modifier'and
            child['attributes']['Flag']in WEAPONS-{weapon.upper()})]
        by_node.setdefault(id(node),(group,node,flags,[]))[3].append((weapon.upper(),replacement))
    for group,node,flags,replaced in by_node.values():
        replaced_flags={flag for flag,_ in replaced};index=next(i for i,item in enumerate(group['children'])if item is node)
        replacements=[item for _,item in replaced]
        if flags&WEAPONS-replaced_flags:
            node['children']=[child for child in node['children']if not(child['name']=='Modifier'and
                child['attributes']['Flag']in replaced_flags)]
            replacements.insert(0,node)
        group['children'][index:index+1]=replacements
    if {weapon for *_,weapon,_ in rows}!=selected.keys():raise ValueError('Incomplete support-grip coverage')
    for group in tree['children']:
        if group['name']=='AnimationGroup':group['attributes']['KeyedAnimationCount']=str(sum(
            node['name']=='KeyframeAnimation'for node in group['children']))
    return art.encode(tree),additions


def prepare_table(raw,read,read_original,target_model,target_locator,basis):
    """Clone only validated rifle-family body poses using actual actor bindings.

    Call before body-only reload duration cloning. First-person resources,
    weapon resources, action selectors and gameplay events are never replaced.
    Shared crouching entries are split so Shotgun retains its existing poses.
    """
    if basis not in(a.CHAZ,a.STORM):raise ValueError('Unknown body animation source basis')
    frames=next((start,end)for tag,start,end,_ in b._records(target_model)if tag==14)
    _,start,_=next(a._chunks(target_model,*frames))
    bones=struct.unpack_from('<I',target_model,start)[0]-1
    if bones not in(22,51):raise ValueError('Unknown player body hierarchy')
    source_locator=read_original(basis[:-4]+('_coop.bllist'if basis==a.STORM else'.bllist'))
    solver=SupportRetarget(read_original(basis),target_model,_grip(source_locator),_grip(target_locator),bones)
    wrist=a._multiply(a._multiply(a._inverse(solver.target[16][0]),a._inverse(solver.target_grip[0])),
                       a._multiply(solver.source_grip[0],solver.source[16][0]))
    if all(abs(matrix[i][j]-a.IDENTITY[i][j])<1e-10
           for matrix in(*solver.maps.values(),wrist)for i in range(3)for j in range(3)):
        return raw,{}
    tree=art.decode(raw)
    if tree['name']!='AnimationSystem':raise ValueError('Expected body animation system')
    references={};selected=[]
    for group in tree['children']:
        if group['name']!='AnimationGroup'or group['attributes'].get('ToolName')not in GROUPS:continue
        for node in group['children']:
            if node['name']!='KeyframeAnimation':continue
            flags={child['attributes']['Flag']for child in node['children']if child['name']=='Modifier'}
            if not flags&FAMILIES or'OUT_OF_VEHICLE'not in flags:continue
            path=art.norm(node['attributes']['Name'])+'.sanm'
            if group['attributes']['ToolName']in('Alert Poses UB','Crouch Alert Poses'):
                stance='CROUCH'if'CROUCH'in flags else'STAND'
                if stance in references and references[stance]!=path:raise ValueError('Ambiguous rifle ready pose')
                references[stance]=path
            selected.append((group,node,flags,path))
    if set(references)!={'STAND','CROUCH'}:raise ValueError('Missing rifle stance references')
    additions={};replacements={};found=set()
    for group,node,flags,path in selected:
        original=_original(path);source=read_original(original);adapted=read(path)
        stance='CROUCH'if'CROUCH'in flags else'STAND'
        additive=bool(struct.unpack_from('<I',source,20)[0]&0x10000000)
        key=path,stance if additive else None
        if key not in replacements:
            if additive:
                if group['attributes']['ToolName']!='Rifle Aim':raise ValueError('Unexpected additive weapon pose')
                reference=references[stance]
                output=solver.bake_delta(read_original(_original(reference)),read(reference),source,adapted)
            else:output,_=solver.bake(source,adapted)
            name=PREFIX+hashlib.sha256(output).hexdigest()[:24]
            additions[name+'.sanm']=output;replacements[key]=name
        replacement=copy.deepcopy(node);replacement['attributes']['Name']=replacements[key]
        replacement['children']=[child for child in replacement['children']if not
            (child['name']=='Modifier'and child['attributes']['Flag']in WEAPONS-FAMILIES)]
        found.update(flags&FAMILIES)
        index=next(i for i,item in enumerate(group['children'])if item is node)
        if flags&(WEAPONS-FAMILIES):
            node['children']=[child for child in node['children']if not
                (child['name']=='Modifier'and child['attributes']['Flag']in FAMILIES)]
            group['children'].insert(index+1,replacement)
        else:group['children'][index]=replacement
    if found!=FAMILIES:raise ValueError('Incomplete rifle-family pose coverage')
    for group in tree['children']:
        if group['name']=='AnimationGroup':group['attributes']['KeyedAnimationCount']=str(sum(
            node['name']=='KeyframeAnimation'for node in group['children']))
    return art.encode(tree),additions
