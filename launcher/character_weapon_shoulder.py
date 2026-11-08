"""Measured two-handed holds for short rigs; preserve the held gun's bore/grip.

Only visual arm rotations are baked. Native action timing, events, masks,
lower-body motion, weapon meshes and attachment calibration remain unchanged.
"""
import copy
import hashlib
import math
import struct

import character_weapon_pose as p

PREFIX='characters/player_two/weaponhold/shoulder/'
ARM_BONES=tuple(range(12,22))
WEAPONS={'RIFLE':'Rifle','SNIPERRIFLE':'SniperRifle','CROSSBOW':'Crossbow'}
# These shorter arms need one shared ready chain across standing/crouching.
# Independently fitted endpoints let native per-bone blends open the grip.
SHARED_RIFLE_HOLD=frozenset(('CassidyPlayerTwo','CassidySpectralSolo',
                            'CassidySpectralPlayerTwo','TalaSolo','TalaCoop','VampireTalaSolo'))
# Right shoulder and left wrist in the held weapon's coordinates. These are
# measured against the actual prepared skin, including the attachment offset.
TALA_LEFT=(
    ((.7102557962,.3233439086,.6252884286),
     (.4693965718,.4444176594,-.7629943277),
     (-.5245985005,.8354293840,.1638737555)),
    (.0604595084,-.0620769768,-.0671180976))
TALA_CROSSBOW_LEFT=TALA_LEFT[0],p.add(TALA_LEFT[1],(0.,.012,-.012))
FITS={name:{'RIFLE':{'STAND':((-.39,.255,-.025),TALA_LEFT,(0.,45.)),
                      'CROUCH':((-.13,.22,-.08),TALA_LEFT,(0.,90.))},
            'SNIPERRIFLE':{'STAND':((-.39,.28,-.06),TALA_LEFT,(0.,45.)),
                          'CROUCH':((-.13,.22,-.08),TALA_LEFT,(0.,90.))},
            'CROSSBOW':{'STAND':((-.39,.28,-.08),TALA_CROSSBOW_LEFT,(0.,45.)),
                        'CROUCH':((-.13,.22,-.08),TALA_CROSSBOW_LEFT,(0.,90.))}}
      for name in('BossTalaSolo','BossTalaCoop')}
MODELS={name:{'49481eb60e07c8286d18332cd937a4e55922b7eca23a95e9db417897b6400a10',
              '4b0262b4f9cda044eb915e6d5141e8c666a2a8bf4fb8c8faf21e84bbafd81143'}
        for name in FITS}

# Measured bulky-rig stock/shoulder clearance; colored uniforms share the rig.
TROOPER_LEFT={('TrooperSolo', 'STAND'): (((0.8666247464, 0.2453697853, 0.4344598723),
                             (0.4023448041, 0.1713130285, -0.8993173216),
                             (-0.2950936143, 0.9541733233, 0.0497409054)),
                            (0.2063046599, -0.0557826542, -0.1140849802)),
 ('TrooperSolo', 'CROUCH'): (((0.8605990998, 0.2258406434, 0.4564705493),
                              (0.4215976247, 0.186887413, -0.8873159889),
                              (-0.2857003079, 0.9560702458, 0.0656213119)),
                             (0.2045590274, -0.0664041141, -0.1107214223)),
 ('TrooperCoop', 'STAND'): (((0.8511143496, 0.2458979033, 0.4638305421),
                             (0.4404248071, 0.1463907231, -0.8857747228),
                             (-0.2857103198, 0.9581780594, 0.0162957615)),
                            (0.206119094, -0.0624436219, -0.090747136)),
 ('TrooperCoop', 'CROUCH'): (((0.8505761837, 0.246863284, 0.4643047085),
                              (0.4400306619, 0.1492945547, -0.8854858931),
                              (-0.2879118023, 0.9574815252, 0.0183590317)),
                             (0.2033754089, -0.0633763563, -0.0905485056))}
TROOPER_FITS={
    'TrooperSolo':{
        'RIFLE':{
            'STAND':((-0.4, 0.2, -0.06),TROOPER_LEFT[('TrooperSolo', 'STAND')],(0, 45)),
            'CROUCH':((-0.4, 0.24, 0.04),TROOPER_LEFT[('TrooperSolo', 'CROUCH')],(-60, 45)),
        },
        'SNIPERRIFLE':{
            'STAND':((-0.35, 0.32, -0.08),TROOPER_LEFT[('TrooperSolo', 'STAND')],(0, 60)),
            'CROUCH':((-0.18, 0.24, -0.08),TROOPER_LEFT[('TrooperSolo', 'CROUCH')],(-60, 60)),
        },
        'CROSSBOW':{
            'STAND':((-0.32, 0.2, -0.1),TROOPER_LEFT[('TrooperSolo', 'STAND')],(-30, 60)),
            'CROUCH':((-0.18, 0.24, -0.08),TROOPER_LEFT[('TrooperSolo', 'CROUCH')],(-60, 60)),
        },
    },
    'TrooperCoop':{
        'RIFLE':{
            'STAND':((-0.4, 0.2, -0.06),TROOPER_LEFT[('TrooperCoop', 'STAND')],(0, 45)),
            'CROUCH':((-0.4, 0.24, 0.04),TROOPER_LEFT[('TrooperCoop', 'CROUCH')],(-60, 75)),
        },
        'SNIPERRIFLE':{
            'STAND':((-0.35, 0.32, -0.08),TROOPER_LEFT[('TrooperCoop', 'STAND')],(0, 60)),
            'CROUCH':((-0.18, 0.24, -0.08),TROOPER_LEFT[('TrooperCoop', 'CROUCH')],(-60, 75)),
        },
        'CROSSBOW':{
            'STAND':((-0.18, 0.24, -0.08),TROOPER_LEFT[('TrooperCoop', 'STAND')],(-60, 60)),
            'CROUCH':((-0.18, 0.24, -0.08),TROOPER_LEFT[('TrooperCoop', 'CROUCH')],(-60, 75)),
        },
    },
}
for _name in ('TrooperSolo', 'BlueTrooperSolo', 'RedTrooperSolo', 'TrooperCoop', 'BlueTrooperCoop', 'RedTrooperCoop'):
    FITS[_name]=TROOPER_FITS['TrooperSolo'if _name.endswith('Solo')else'TrooperCoop']
MODELS.update({'TrooperSolo': {'697d68592b6c53ce250f22e298d2770c6a8de8f4c990219b35f4b0128b2aa478'},
 'BlueTrooperSolo': {'37bb3be6b4578ce57d3595ac7a2b034952da255949c4322db2ab8259827b3a3b'},
 'RedTrooperSolo': {'52f07f4e0568cfde03c28467ccd3e5f73ef06b40fd9327b7a7af5558e65e17ae'},
 'TrooperCoop': {'697d68592b6c53ce250f22e298d2770c6a8de8f4c990219b35f4b0128b2aa478'},
 'BlueTrooperCoop': {'37bb3be6b4578ce57d3595ac7a2b034952da255949c4322db2ab8259827b3a3b'},
 'RedTrooperCoop': {'52f07f4e0568cfde03c28467ccd3e5f73ef06b40fd9327b7a7af5558e65e17ae'}})

# Smaller rigs retain their model-specific support-hand contact.
FITS.update({
    'CassidySolo':{
        'RIFLE':{
            'STAND':((-0.39, 0.255, -0.025),None,(-30, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-30.0, 90.0)),
        },
        'SNIPERRIFLE':{
            'STAND':((-0.39, 0.28, -0.06),None,(-75, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-60.0, 90.0)),
        },
        'CROSSBOW':{
            'STAND':((-0.39, 0.28, -0.08),None,(-45, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-45.0, 90.0)),
        },
    },
    'CassidyPlayerTwo':{
        'RIFLE':{
            'STAND':((-0.39, 0.255, -0.025),None,(-30, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-15.0, 90.0)),
        },
        'SNIPERRIFLE':{
            'STAND':((-0.39, 0.28, -0.06),None,(-75, 30)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-45.0, 90.0)),
        },
        'CROSSBOW':{
            'STAND':((-0.39, 0.28, -0.08),None,(-45, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-45.0, 90.0)),
        },
    },
    'CassidySpectralSolo':{
        'RIFLE':{
            'STAND':((-0.39, 0.255, -0.025),None,(15, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-45.0, 90.0)),
        },
        'SNIPERRIFLE':{
            'STAND':((-0.39, 0.28, -0.06),None,(-75, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-45.0, 90.0)),
        },
        'CROSSBOW':{
            'STAND':((-0.39, 0.28, -0.08),None,(-15, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-60.0, 90.0)),
        },
    },
    'CassidySpectralPlayerTwo':{
        'RIFLE':{
            'STAND':((-0.39, 0.255, -0.025),None,(15, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-15.0, 90.0)),
        },
        'SNIPERRIFLE':{
            'STAND':((-0.39, 0.28, -0.06),None,(-90, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-60.0, 90.0)),
        },
        'CROSSBOW':{
            'STAND':((-0.39, 0.28, -0.08),None,(-15, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-75.0, 90.0)),
        },
    },
    'TalaSolo':{
        'RIFLE':{
            'STAND':((-0.39, 0.255, -0.025),None,(-30, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(0.0, 120.0)),
        },
        'SNIPERRIFLE':{
            'STAND':((-0.39, 0.28, -0.06),None,(-30, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-45.0, 120.0)),
        },
        'CROSSBOW':{
            'STAND':((-0.39, 0.28, -0.08),None,(-45, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-45.0, 120.0)),
        },
    },
    'TalaCoop':{
        'RIFLE':{
            'STAND':((-0.39, 0.255, -0.025),None,(-45, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(15.0, 90.0)),
        },
        'SNIPERRIFLE':{
            'STAND':((-0.39, 0.28, -0.06),None,(-30, 15)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-30.0, 90.0)),
        },
        'CROSSBOW':{
            'STAND':((-0.39, 0.28, -0.08),None,(-30, 0)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-75.0, 90.0)),
        },
    },
    'VampireTalaSolo':{
        'RIFLE':{
            'STAND':((-0.39, 0.255, -0.025),None,(-15, 15)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-45.0, 150.0)),
        },
        'SNIPERRIFLE':{
            'STAND':((-0.39, 0.28, -0.06),None,(-75, 15)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-60.0, 150.0)),
        },
        'CROSSBOW':{
            'STAND':((-0.39, 0.28, -0.08),None,(-60, 15)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-60.0, 150.0)),
        },
    },
    'VampireTalaCoop':{
        'RIFLE':{
            'STAND':((-0.39, 0.255, -0.025),None,(0, 45)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-90.0, 135.0)),
        },
        'SNIPERRIFLE':{
            'STAND':((-0.39, 0.28, -0.06),None,(0, 30)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-45.0, 135.0)),
        },
        'CROSSBOW':{
            'STAND':((-0.39, 0.28, -0.08),None,(-15, 15)),
            'CROUCH':((-0.13, 0.22, -0.08),None,(-60.0, 135.0)),
        },
    },
})
MODELS.update({'CassidySolo': {'ab5cd1e6e409eeb650297932503f04eb408ef1ace669b49397f4e07ca36f4eef'},
 'CassidyPlayerTwo': {'ab5cd1e6e409eeb650297932503f04eb408ef1ace669b49397f4e07ca36f4eef'},
 'CassidySpectralSolo': {'08d3c57bc2e28f5a38c26e86f2798b8fa60f47c5552d5ea7cef588ddaddf8ad0'},
 'CassidySpectralPlayerTwo': {'08d3c57bc2e28f5a38c26e86f2798b8fa60f47c5552d5ea7cef588ddaddf8ad0'},
 'TalaSolo': {'61ec2ceac3ebf48f560413492ef566918cc4b6e17ea2348ca8318a5db7899efb'},
 'TalaCoop': {'61ec2ceac3ebf48f560413492ef566918cc4b6e17ea2348ca8318a5db7899efb'},
 'VampireTalaSolo': {'9d1691d4fa15f1939dbd4c64479c28693c9ce701e78b1745868a1dad2cbb8c5f'},
 'VampireTalaCoop': {'9d1691d4fa15f1939dbd4c64479c28693c9ce701e78b1745868a1dad2cbb8c5f'}})

def _shared_shift(centers,radii):
    """Closest common displacement in two arm-reach balls (closed form)."""
    zero=(0.,0.,0.)
    if all(p.length(c)<=r for c,r in zip(centers,radii)):return zero
    for i in(0,1):
        center=centers[i];distance=p.length(center)
        point=zero if distance<=radii[i]else p.scale(center,1-radii[i]/distance)
        if p.length(p.sub(point,centers[1-i]))<=radii[1-i]+1e-9:return point
    difference=p.sub(centers[1],centers[0]);distance=p.length(difference)
    if distance>=sum(radii) or distance<=abs(radii[0]-radii[1]):
        raise ValueError('Two-handed hold cannot preserve both arm lengths')
    axis=p.scale(difference,1/distance)
    along=(radii[0]**2-radii[1]**2+distance**2)/(2*distance)
    center=p.add(centers[0],p.scale(axis,along))
    radius=math.sqrt(max(0.,radii[0]**2-along**2))
    toward=p.sub(p.scale(center,-1),p.scale(axis,-p.dot(center,axis)))
    if p.length(toward)<1e-10:
        toward=p.cross(axis,(0.,1.,0.)if abs(axis[1])<.9 else(1.,0.,0.))
    return p.add(center,p.scale(p.unit(toward),radius))


def fit_pose(local,parents,grip,offset,anchor,left,*,holding=True,poles=(0.,0.)):
    before=p.world(local,parents)
    locator=grip[0],p.add(grip[1],p.scale(grip[0][0],offset))
    original=p.mul(locator,before[16])
    desired=original[0],p.sub(before[13][1],p.rotate(anchor,original[0]))
    targets=[]
    for wrist in(15,20):
        relative=left if wrist==20 and holding else p.mul(before[wrist],p.inverse(original))
        targets.append(p.mul(relative,desired))
    centers=tuple(p.sub(before[s][1],target[1])for s,target in zip((13,18),targets))
    radii=tuple(.995*(p.length(p.sub(before[e][1],before[s][1]))+
                     p.length(p.sub(before[w][1],before[e][1])))for s,e,w in((13,14,15),(18,19,20)))
    shift=_shared_shift(centers,radii);result=dict(before)
    for (shoulder,elbow,wrist,joint),target in zip(((13,14,15,16),(18,19,20,21)),targets):
        s,e,w=(before[b][1]for b in(shoulder,elbow,wrist))
        middle,endpoint=p.solve(s,e,w,p.add(target[1],shift))
        if shoulder==18 and holding:
            axis=p.unit(p.sub(endpoint,s));center=p.add(s,p.scale(axis,p.dot(p.sub(middle,s),axis)))
            down=p.rotate((0.,-1.,0.),original[0]);down=p.unit(p.sub(down,p.scale(axis,p.dot(down,axis))))
            middle=p.add(center,p.scale(down,p.length(p.sub(middle,center))))
        angle=poles[0 if shoulder==13 else 1]if holding else 0.
        if angle:
            axis=p.unit(p.sub(endpoint,s));center=p.add(s,p.scale(axis,p.dot(p.sub(middle,s),axis)))
            radial=p.sub(middle,center);theta=math.radians(angle)
            middle=p.add(center,p.add(p.scale(radial,math.cos(theta)),p.scale(p.cross(axis,radial),math.sin(theta))))
        result[shoulder]=p.a._multiply(before[shoulder][0],p.align(p.sub(e,s),p.sub(middle,s))),s
        result[elbow]=p.a._multiply(before[elbow][0],p.align(p.sub(w,e),p.sub(endpoint,middle))),middle
        result[wrist]=target[0],endpoint
        result[joint]=p.mul(p.mul(before[joint],p.inverse(before[wrist])),result[wrist])
    return p.localize(result,parents)


def shared_hold(local,reference,parents):
    """Keep a two-handed ready chain together through native stance blends.

    Clavicles follow the current torso and gun orientation. Distal arm rotations
    share one measured pose; translations, body motion and bore stay authored.
    """
    source=p.world(reference,parents);target=p.world(local,parents)
    rotation=p.a._multiply(p.a._inverse(source[16][0]),target[16][0])
    result=dict(local)
    for bone in ARM_BONES:result[bone]=reference[bone][0],local[bone][1]
    for bone in(12,17):
        world=p.a._multiply(source[bone][0],rotation)
        result[bone]=p.a._multiply(world,p.a._inverse(target[parents[bone]][0])),local[bone][1]
    return result


class ShoulderHold(p.SupportRetarget):
    arm_bones=ARM_BONES

    def prepare(self,data,reference,anchor,left,offset,*,holding=True,poles=(0.,0.),shared=None):
        clip=p.Clip(data,self.bones,True);base=p.Clip(reference,self.bones).pose(self.target,.5)
        if left is None:
            ready=p.world(base,self.parents)
            locator=self.target_grip[0],p.add(self.target_grip[1],p.scale(self.target_grip[0][0],offset))
            left=p.mul(ready[20],p.inverse(p.mul(locator,ready[16])))
        phases={0.,1.}
        for times,_ in clip.tracks.values():phases.update(times)
        times=sorted(phases)
        phases.update((a+b)/2 for a,b in zip(times,times[1:])if b-a>1/60)
        additive=bool(clip.flags&0x10000000)
        corrected=fit_pose(base,self.parents,self.target_grip,offset,anchor,left,poles=poles)
        if shared is not None:corrected=shared_hold(corrected,shared,self.parents)
        identity={b:(p.a.IDENTITY,(0.,0.,0.))for b in base}
        mask=struct.unpack_from('<'+'I'*self.bones,data,clip.parts[1]['keys'])if 1 in clip.parts else(0,)*self.bones
        cache={}
        def sample(phase):
            if phase not in cache:
                pose=clip.pose(identity if additive else self.target,phase)
                if additive:
                    pose={b:base[b]if mask[b]else(p.a._multiply(base[b][0],pose[b][0]),p.add(base[b][1],pose[b][1]))for b in base}
                desired=fit_pose(pose,self.parents,self.target_grip,offset,anchor,left,holding=holding,poles=poles)
                if shared is not None:desired=shared_hold(desired,shared,self.parents)
                if additive:desired={b:(p.a._multiply(p.a._inverse(corrected[b][0]),desired[b][0]),(0.,0.,0.))for b in base}
                cache[phase]=desired
            return cache[phase]
        return self._encode_rotations(clip,sample,phases)


def prepare_table(raw,read,read_original,model,locator,basis,actor,offsets):
    fits=FITS.get(actor)
    if not fits:return raw,{}
    if basis not in(p.a.CHAZ,p.a.STORM):raise ValueError('Unsupported shoulder-fit animation basis')
    if hashlib.sha256(model).hexdigest()not in MODELS[actor]:
        raise ValueError('Unrecognized shoulder-fit body geometry')
    tree=p.art.decode(raw);references={}
    if tree['name']!='AnimationSystem':raise ValueError('Expected shoulder-fit animation system')
    for group in tree['children']:
        name=group['attributes'].get('ToolName')
        if name not in('Alert Poses UB','Crouch Alert Poses'):continue
        for node in group['children']:
            if node['name']!='KeyframeAnimation' or node['attributes'].get('AnimationID')!='IDLE':continue
            flags={c['attributes']['Flag']for c in node['children']if c['name']=='Modifier'}
            for flag in fits.keys()&flags:
                key=flag,'CROUCH'if name=='Crouch Alert Poses'else'STAND'
                if key in references:raise ValueError('Duplicate shoulder-fit ready reference')
                references[key]=p.art.norm(node['attributes']['Name'])+'.sanm'
    if set(references)!={(flag,stance)for flag in fits for stance in('STAND','CROUCH')}:
        raise ValueError('Missing shoulder-fit ready reference')
    bones=struct.unpack_from('<I',read(next(iter(references.values()))),8)[0]
    source_locator=basis[:-4]+('_coop.bllist'if basis==p.a.STORM else'.bllist')
    solver=ShoulderHold(read_original(basis),model,p._grip(read_original(source_locator)),p._grip(locator),bones)
    shared=None
    if actor in SHARED_RIFLE_HOLD:
        anchor,left,poles=fits['RIFLE']['STAND']
        ready=p.Clip(read(references['RIFLE','STAND']),bones).pose(solver.target,.5)
        world=p.world(ready,solver.parents);offset=offsets.get((actor,'Rifle'),(0.,0.))[0]
        grip=solver.target_grip[0],p.add(solver.target_grip[1],p.scale(solver.target_grip[0][0],offset))
        left=left or p.mul(world[20],p.inverse(p.mul(grip,world[16])))
        shared=fit_pose(ready,solver.parents,solver.target_grip,offset,anchor,left,poles=poles)
    additions={};cache={}
    for group in tree['children']:
        name=group['attributes'].get('ToolName','')
        if name not in('Alert Poses UB','Crouch Alert Poses','Rifle Aim','Weapon Shoot','Reload Rifle','Reload Sniper Rifle','Reload Crossbow'):continue
        rows=[]
        for node in group['children']:
            if node['name']!='KeyframeAnimation':rows.append(node);continue
            flags={c['attributes']['Flag']for c in node['children']if c['name']=='Modifier'}
            selected=flags&fits.keys()
            if not selected:rows.append(node);continue
            path=p.art.norm(node['attributes']['Name'])+'.sanm'
            if path.startswith(PREFIX):raise ValueError('Shoulder correction already applied')
            if flags&p.WEAPONS-selected:
                original=copy.deepcopy(node);original['children']=[c for c in original['children']if not(c['name']=='Modifier'and c['attributes']['Flag']in selected)];rows.append(original)
            stances=('CROUCH',)if'CROUCH'in flags else('STAND',)if'STAND'in flags else('STAND','CROUCH')
            for flag in sorted(selected):
                for stance in stances:
                    key=path,flag,stance,not name.startswith('Reload ')
                    if key not in cache:
                        settings=fits[flag][stance]
                        data=solver.prepare(read(path),read(references[flag,stance]),*settings[:2],offsets.get((actor,WEAPONS[flag]),(0.,0.))[0],holding=not name.startswith('Reload '),poles=settings[2]if len(settings)>2 else(0.,0.),shared=shared if flag=='RIFLE'and not name.startswith('Reload ')else None)
                        target=PREFIX+hashlib.sha256(data).hexdigest()[:24];cache[key]=target;additions[target+'.sanm']=data
                    replacement=copy.deepcopy(node);replacement['attributes']['Name']=cache[key]
                    replacement['children']=[c for c in replacement['children']if not(c['name']=='Modifier'and c['attributes']['Flag']in p.WEAPONS-{flag})]
                    if not flags&{'STAND','CROUCH'}:replacement['children'].append({'name':'Modifier','attributes':{'Flag':stance},'value':None,'children':[]})
                    rows.append(replacement)
        group['children']=rows;group['attributes']['KeyedAnimationCount']=str(sum(n['name']=='KeyframeAnimation'for n in rows))
    return p.art.encode(tree),additions
