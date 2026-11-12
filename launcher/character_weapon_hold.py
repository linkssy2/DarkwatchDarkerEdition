"""Stable two-handed holding poses retain native torso and lower-body motion.

Shotgun movement and independent aiming disagree at the forearms. Hold the
actual ready grip below the chest; authored fire, pump and reload still run.
"""
import copy
import hashlib
import math
import struct

import character_weapon_pose as p
import character_spectral_hands as skin
import character_weapon_shoulder as shoulder

PREFIX='characters/player_two/weaponhold/'
HOLD_BONES=tuple(range(12,22))
ROCKET_MODEL='accessories/weapons/dwrailrocket/base_pov_dwrailrocket.rx1'

# Measured whole-hand contact corrections against the native fore-end surfaces.
# All other ready contacts already intersect their authored support surface.
SUPPORT_CONTACTS={
    ('CassidySolo','Shotgun','STAND'):(0.0, 0.012846754, 0.018419108),
    ('CassidySolo','RocketLauncher','CROUCH'):(1.9045e-05, 0.019662036, 0.001776845),
    ('CassidyPlayerTwo','Shotgun','STAND'):(0.000137549, -1.433e-06, 0.008610435),
    ('CassidyPlayerTwo','RocketLauncher','CROUCH'):(1.4232e-05, 0.015379967, 0.0007424),
    ('CassidySpectralSolo','Shotgun','STAND'):(0.0, 0.007962703, 0.02658934),
    ('CassidySpectralSolo','RocketLauncher','CROUCH'):(2.9151e-05, 0.032499661, 0.000670469),
    ('CassidySpectralPlayerTwo','Shotgun','STAND'):(0.00016124, -1.68e-06, 0.010093519),
    ('CassidySpectralPlayerTwo','RocketLauncher','CROUCH'):(2.4537e-05, 0.028988306, -0.000828152),
    ('TalaSolo','Shotgun','STAND'):(0.0, 0.022018733, 0.033600356),
    ('TalaSolo','RocketLauncher','CROUCH'):(1.5508e-05, 0.023657817, -0.005073869),
    ('TalaCoop','Shotgun','STAND'):(0.000373289, -3.889e-06, 0.023367615),
    ('TalaCoop','RocketLauncher','CROUCH'):(1.0623e-05, 0.019255845, -0.006076064),
    ('VampireTalaSolo','Shotgun','STAND'):(-0.0, -0.017259765, 0.008706124),
    ('VampireTalaCoop','Shotgun','STAND'):(0.0, -0.004358584, 0.001846038),
    ('BossTalaSolo','Shotgun','STAND'):(0.0, -0.011171638, 0.005393677),
}
CONTACT_MODELS={
    'CassidySolo':'ab5cd1e6e409eeb650297932503f04eb408ef1ace669b49397f4e07ca36f4eef',
    'CassidyPlayerTwo':'ab5cd1e6e409eeb650297932503f04eb408ef1ace669b49397f4e07ca36f4eef',
    'CassidySpectralSolo':'08d3c57bc2e28f5a38c26e86f2798b8fa60f47c5552d5ea7cef588ddaddf8ad0',
    'CassidySpectralPlayerTwo':'08d3c57bc2e28f5a38c26e86f2798b8fa60f47c5552d5ea7cef588ddaddf8ad0',
    'TalaSolo':'61ec2ceac3ebf48f560413492ef566918cc4b6e17ea2348ca8318a5db7899efb',
    'TalaCoop':'61ec2ceac3ebf48f560413492ef566918cc4b6e17ea2348ca8318a5db7899efb',
    'VampireTalaSolo':'9d1691d4fa15f1939dbd4c64479c28693c9ce701e78b1745868a1dad2cbb8c5f',
    'VampireTalaCoop':'9d1691d4fa15f1939dbd4c64479c28693c9ce701e78b1745868a1dad2cbb8c5f',
    # Normal and private shape variants have identical head/arm/hand geometry,
    # weights, inverse binds and the entire 51-bone hierarchy.
    'BossTalaSolo':('49481eb60e07c8286d18332cd937a4e55922b7eca23a95e9db417897b6400a10',
                    '4b0262b4f9cda044eb915e6d5141e8c666a2a8bf4fb8c8faf21e84bbafd81143'),
}


class RocketClearance:
    """Separate the rigid receiver from the posed head without stretching arms."""
    def __init__(self,model,weapon,actor):
        if hashlib.sha256(weapon).hexdigest()!='d595dd40e1319180ad5bb8e86b92a3ca4cd6294a6d7649819148532116f8fc88':
            raise ValueError('Unrecognized Rocket receiver geometry')
        body=skin._geometry(model,1 if actor.startswith('CassidySpectral')else 0)
        self.head=[tuple((bone,skin._point(point,body['inverse'][bone]),weight)for bone,weight in weights.items())
                   for point,weights in zip(body['positions'],body['weights'])if sum(weights.get(bone,0.)for bone in(10,11))>.5]
        receiver=skin._geometry(weapon,0,allowed_bones=(5,))
        self.triangles=[triangle for triangle in receiver['triangles']if all(set(receiver['weights'][vertex])=={0}for vertex in triangle)]
        self.vertices=receiver['positions']
        if not self.head or len(self.triangles)!=1274:raise ValueError('Incomplete Rocket head/receiver clearance geometry')

    def apply(self,pose,locator,parents):
        head=[]
        for vertex in self.head:
            point=(0.,0.,0.)
            for bone,local,weight in vertex:point=p.add(point,p.scale(p.add(p.rotate(local,pose[bone][0]),pose[bone][1]),weight))
            head.append(point)
        up=p.unit(p.sub(pose[11][1],pose[9][1]));side=p.sub(pose[13][1],pose[18][1])
        side=p.unit(p.sub(side,p.scale(up,p.dot(side,up))));forward=p.unit(p.cross(side,up));axes=(side,up,forward)
        project=lambda point:tuple(p.dot(point,axis)for axis in axes)
        head=[project(point)for point in head];low=tuple(min(point[i]for point in head)for i in range(3));high=tuple(max(point[i]for point in head)for i in range(3))
        mount=p.mul(locator,pose[16]);vertices=[project(p.add(p.rotate(point,mount[0]),mount[1]))for point in self.vertices]
        nearest=None
        for triangle in self.triangles:
            points=[vertices[index]for index in triangle]
            if any(max(point[i]for point in points)<low[i]or min(point[i]for point in points)>high[i]for i in(1,2)):continue
            for axis,edge,sign in((1,low[1],1),(1,high[1],-1),(2,low[2],1),(2,high[2],-1)):
                clipped=[]
                for first,second in zip(points,points[1:]+points[:1]):
                    inside=(first[axis]-edge)*sign>=0;other=(second[axis]-edge)*sign>=0
                    if inside:clipped.append(first)
                    if inside!=other:clipped.append(p.add(first,p.scale(p.sub(second,first),(edge-first[axis])/(second[axis]-first[axis]))))
                points=clipped
                if not points:break
            if points:
                value=min(point[0]for point in points);nearest=value if nearest is None else min(nearest,value)
        distance=max(0.,high[0]-nearest+.005)if nearest is not None else 0.
        if not distance:return p.localize(pose,parents)
        shift=p.scale(side,distance);result=dict(pose)
        for shoulder,elbow,wrist,joint in((13,14,15,16),(18,19,20,21)):
            s,e,w=(pose[bone][1]for bone in(shoulder,elbow,wrist));middle,endpoint=p.solve(s,e,w,p.add(w,shift))
            result[shoulder]=p.a._multiply(pose[shoulder][0],p.align(p.sub(e,s),p.sub(middle,s))),s
            result[elbow]=p.a._multiply(pose[elbow][0],p.align(p.sub(w,e),p.sub(endpoint,middle))),middle
            result[wrist]=pose[wrist][0],endpoint;result[joint]=p.mul(p.mul(pose[joint],p.inverse(pose[wrist])),result[wrist])
        return p.localize(result,parents)


class StableHold(p.SupportRetarget):
    arm_bones=HOLD_BONES
    anchor=None
    offset=0.
    clearance=None
    contact=None

    def fit_contacts(self,before,after,desired):
        if self.anchor is not None:
            locator=self.target_grip[0],p.add(self.target_grip[1],p.scale(self.target_grip[0][0],self.offset))
            desired=p.mul(self.anchor,p.mul(locator,after[16]))
        elif self.contact is not None:
            gun=p.mul(self.target_grip,after[16])
            desired=desired[0],p.add(desired[1],p.rotate(self.contact,gun[0]))
        result=super().fit_contacts(before,after,desired)
        return self.clearance.apply(p.world(result,self.parents),self.target_grip,self.parents)if self.clearance else result

    def bake_hold(self,data,hold):
        clip=p.Clip(data,self.bones);phases={0.,1.}
        for times,_ in clip.tracks.values():phases.update(times)
        return self._encode_rotations(clip,lambda phase:hold,phases)

    def bake_delta(self,source_base,adapted_base,source_delta,adapted_delta,*,new_grip_offset=None):
        native_base=p.Clip(source_base,22);target_base=p.Clip(adapted_base,self.bones)
        native=p.Clip(source_delta,22,True);target=p.Clip(adapted_delta,self.bones,True)
        if not(native.flags&target.flags&0x10000000):raise ValueError('Expected additive held-weapon action')
        original=native_base.pose(self.source,.5);before=target_base.pose(self.target,.5)
        corrected=self.correct(original,before,new_grip_offset=new_grip_offset)
        def combined(base,clip,phase):
            delta=clip.pose({bone:(p.a.IDENTITY,(0.,0.,0.))for bone in base},phase)
            return {bone:(p.a._multiply(value[0],delta[bone][0]),p.add(value[1],delta[bone][1]))for bone,value in base.items()}
        phases={0.,1.};cache={}
        for clip in(native,target):
            for times,_ in clip.tracks.values():phases.update(times)
        # A coupled hand may need to move even when its original track had no
        # key at the gun's recoil peak. Share authored times and their midpoints.
        times=sorted(phases);phases.update((a+b)/2 for a,b in zip(times,times[1:]))
        def sample(phase):
            if phase not in cache:
                desired=self.correct(combined(original,native,phase),combined(before,target,phase),new_grip_offset=new_grip_offset)
                cache[phase]={bone:(p.a._multiply(p.a._inverse(corrected[bone][0]),desired[bone][0]),(0.,0.,0.))for bone in before}
            return cache[phase]
        return self._encode_rotations(target,sample,phases)


def _prepare_weapon(raw,read,read_original,target_model,target_locator,basis,actor,offsets,weapon):
    if actor not in p.GRIP_ACTORS or basis not in(p.a.CHAZ,p.a.STORM):raise ValueError('Unknown held-weapon actor basis')
    tree=p.art.decode(raw)
    if tree['name']!='AnimationSystem':raise ValueError('Expected held-weapon body animation system')
    frames=next((start,end)for tag,start,end,_ in p.b._records(target_model)if tag==14)
    _,start,_=next(p.a._chunks(target_model,*frames));bones=struct.unpack_from('<I',target_model,start)[0]-1
    if bones not in(22,51):raise ValueError('Unknown held-weapon body hierarchy')
    source_locator=read_original(basis[:-4]+('_coop.bllist'if basis==p.a.STORM else'.bllist'))
    solver=StableHold(read_original(basis),target_model,p._grip(source_locator),p._grip(target_locator),bones)
    solver.offset=offsets.get((actor,weapon),(0.,0.))[0]
    if weapon=='RocketLauncher':solver.clearance=RocketClearance(target_model,read_original(ROCKET_MODEL),actor)
    flag='SHOTGUN'if weapon=='Shotgun'else'RAILRCKT'
    aim_group='Shotgun Aim'if weapon=='Shotgun'else'Rocket Launcher Aim'
    movement='Movement UB '+weapon;crouch_movement='Crouch Movement '+('Rifle'if weapon=='Shotgun'else weapon)
    references={};selected=[]
    for group in tree['children']:
        if group['name']!='AnimationGroup':continue
        name=group['attributes'].get('ToolName')
        if name not in('Alert Poses UB','Crouch Alert Poses',movement,crouch_movement,aim_group,'Weapon Shoot','Reload '+weapon):continue
        for node in group['children']:
            if node['name']!='KeyframeAnimation':continue
            flags={child['attributes']['Flag']for child in node['children']if child['name']=='Modifier'}
            if flag not in flags:continue
            path=p.art.norm(node['attributes']['Name'])+'.sanm';stance='CROUCH'if'CROUCH'in flags else'STAND'
            if name in('Alert Poses UB','Crouch Alert Poses'):references[stance]=path
            if name=='Reload '+weapon and not solver.offset:continue
            selected.append((group,node,flags,path,stance))
    if set(references)!={'STAND','CROUCH'}:raise ValueError('Missing two-handed holding reference')
    reference_data={};holds={};anchors={}
    for stance,path in references.items():
        adapted=read(path);source=read_original(p._original(path))
        before=p.world(p.Clip(adapted,bones).pose(solver.target,.5),solver.parents)
        anchors[stance]=p.mul(before[20],p.inverse(p.mul(solver.target_grip,before[16])))
        contact=SUPPORT_CONTACTS.get((actor,weapon,stance))
        if contact:
            expected=CONTACT_MODELS[actor]
            if isinstance(expected,str):expected=(expected,)
            if hashlib.sha256(target_model).hexdigest()not in expected:
                raise ValueError('Unrecognized support-hand contact model')
            rotation,position=anchors[stance]
            anchors[stance]=rotation,p.add(position,contact)
        solver.anchor=anchors[stance]
        holds[stance]=solver.sample(p.Clip(source,22),p.Clip(adapted,bones),.5,new_grip_offset=solver.offset)
        reference_data[stance]=source,adapted
    additions={};cache={}
    for group,node,flags,path,stance in selected:
        kind=group['attributes']['ToolName'];data=read(path)
        stances=('STAND','CROUCH')if kind=='Weapon Shoot'and not flags&{'STAND','CROUCH'}else(stance,)
        replacements=[]
        for stance in stances:
            key=path,stance,kind
            if key not in cache:
                solver.anchor=anchors[stance]if kind==aim_group or weapon=='RocketLauncher'and kind=='Weapon Shoot'else None
                solver.contact=SUPPORT_CONTACTS.get((actor,weapon,stance))if kind=='Weapon Shoot'and weapon=='Shotgun'else None
                if kind in(aim_group,'Weapon Shoot'):
                    source=read_original(p._original(path));source_base,adapted_base=reference_data[stance]
                    output=solver.bake_delta(source_base,adapted_base,source,data,new_grip_offset=solver.offset)
                elif kind=='Reload '+weapon:output=solver.bake_grip(data,solver.offset)
                else:output=solver.bake_hold(data,holds[stance])
                name=PREFIX+hashlib.sha256(output).hexdigest()[:24];cache[key]=name;additions[name+'.sanm']=output
            replacement=copy.deepcopy(node);replacement['attributes']['Name']=cache[key]
            replacement['children']=[child for child in replacement['children']if not(child['name']=='Modifier'and child['attributes']['Flag']in p.WEAPONS-{flag})]
            if len(stances)>1:replacement['children'].append({'name':'Modifier','attributes':{'Flag':stance},'value':None,'children':[]})
            replacements.append(replacement)
        index=next(i for i,item in enumerate(group['children'])if item is node)
        if flags&(p.WEAPONS-{flag}):
            node['children']=[child for child in node['children']if not(child['name']=='Modifier'and child['attributes']['Flag']==flag)]
            replacements.insert(0,node)
        group['children'][index:index+1]=replacements
    for group in tree['children']:
        if group['name']=='AnimationGroup':group['attributes']['KeyedAnimationCount']=str(sum(node['name']=='KeyframeAnimation'for node in group['children']))
    return p.art.encode(tree),additions


def prepare_table(raw,read,read_original,target_model,target_locator,basis,actor,offsets):
    additions={}
    def composed(path):return additions[path]if path in additions else read(path)
    for weapon in('Shotgun','RocketLauncher'):
        raw,clips=_prepare_weapon(raw,composed,read_original,target_model,target_locator,basis,actor,offsets,weapon)
        additions.update(clips)
    return raw,additions


MASCULINE_GAIT_ACTORS = {'Chaz', 'JerichoCoop', 'CivilianJerichoSolo', 'CivilianJerichoCoop',
                         'TrooperSolo', 'TrooperCoop', 'BlueTrooperSolo', 'BlueTrooperCoop',
                         'RedTrooperSolo', 'RedTrooperCoop'}


class AimedMotion(p.SupportRetarget):
    # Preserve the pinned base conversion; campaign head stabilization follows it.
    arm_bones=(7,8,9,*HOLD_BONES)

    def relaxed_arm(self,base):
        pose=p.world(base,self.parents);local=dict(base)
        up=p.unit(p.sub(pose[9][1],pose[7][1]));side=p.sub(pose[18][1],pose[13][1])
        side=p.unit(p.sub(side,p.scale(up,p.dot(side,up))));forward=p.unit(p.cross(side,up))
        for bone,child,reach in((18,19,-.05),(19,20,.18)):
            pose=p.world(local,self.parents)
            direction=p.add(p.scale(up,-1.),p.add(p.scale(side,.10),p.scale(forward,reach)))
            rotation=p.a._multiply(pose[bone][0],p.align(p.sub(pose[child][1],pose[bone][1]),direction))
            local[bone]=p.a._multiply(rotation,p.a._inverse(pose[self.parents[bone]][0])),local[bone][1]
        return local

    def masculine_free_arm(self, data):
        """Author standing locomotion only; crouch retains its stance-specific arm pose."""
        clip = p.Clip(data, self.bones)
        self.arm_bones = (18, 19, 20)
        reference = clip.pose(self.target, .5)
        def axes(local):
            world = p.world(local, self.parents)
            up = p.unit(p.sub(world[9][1], world[7][1]))
            side = p.sub(world[18][1], world[13][1])
            side = p.unit(p.sub(side, p.scale(up, p.dot(side, up))))
            return world, up, side, p.unit(p.cross(side, up))
        def swing(phase):
            world, up, side, forward = axes(clip.pose(self.target, phase))
            arm = p.sub(world[19][1], world[18][1])
            return math.atan2(p.dot(arm, forward), -p.dot(arm, up))
        values = [swing(i / 60) for i in range(61)]
        middle = (min(values) + max(values)) * .5
        extent = (max(values) - min(values)) * .5
        cache = {}
        def sample(phase):
            if phase in cache:
                return cache[phase]
            local = clip.pose(self.target, phase)
            # Retain shoulder motion, but prevent source arm twist from steering the hand inward.
            for bone in (18, 19, 20):
                local[bone] = reference[bone][0], local[bone][1]
            world, up, side, forward = axes(local)
            stride = max(-1., min(1., (swing(phase) - middle) / extent)) if extent > .01 else 0.
            theta = .38 * stride
            # Reference walks open the elbow behind the hip and bend it on the forward swing.
            bend = .32 + .22 * stride
            for bone, child, angle, tilt in ((18, 19, theta, .48), (19, 20, theta + bend, .16)):
                direction = p.add(p.scale(up, -math.cos(angle) * math.cos(tilt)),
                                  p.add(p.scale(forward, math.sin(angle)),
                                        p.scale(side, math.cos(angle) * math.sin(tilt))))
                world = p.world(local, self.parents)
                rotation = p.a._multiply(world[bone][0], p.align(p.sub(world[child][1], world[bone][1]), direction))
                local[bone] = p.a._multiply(rotation, p.a._inverse(world[self.parents[bone]][0])), local[bone][1]
            cache[phase] = local
            return local
        return self._encode_rotations(clip, sample, (), synchronize=False)

    def bake_motion(self,data,ready,*,free_arm=False):
        # Preserve the authored swing below the shoulder instead of the raised
        # running pose; the trigger arm keeps the native aim-mixing basis.
        self.arm_bones=(7,8,9,*range(12,17))if free_arm else(7,8,9,*HOLD_BONES)
        clip=p.Clip(data,self.bones)
        base=p.Clip(ready,self.bones).pose(self.target,.5)
        if any(clip.parts[4]['indices'][bone]==p.MISSING for bone in self.arm_bones):
            raise ValueError('Incomplete aimed-motion rotation chain')
        output=bytearray(self._encode_rotations(clip,lambda phase:base,{0.,1.}))
        if free_arm:
            relaxed=self.relaxed_arm(base);cache={};self.arm_bones=tuple(range(17,22))
            def sample(phase):
                if phase not in cache:
                    local=clip.pose(self.target,phase)
                    for bone in self.arm_bones:
                        rest=p.a._to_quaternion(relaxed[bone][0]);swing=p.a._to_quaternion(local[bone][0])
                        if p.dot(rest,swing)<0:swing=p.scale(swing,-1.)
                        rotation=p.unit(p.add(p.scale(rest,.55),p.scale(swing,.45)))
                        local[bone]=p.a._quaternion_matrix(rotation),local[bone][1]
                    cache[phase]=local
                return cache[phase]
            output=bytearray(self._encode_rotations(p.Clip(bytes(output),self.bones),sample,(),synchronize=False))
        part=p.b.sections(output,self.bones)[1].get(8)
        if part is None:raise ValueError('Missing aimed-motion socket translations')
        for bone in(16,21):
            first=part['indices'][bone]
            if first==p.MISSING:raise ValueError('Missing aimed-motion socket translation')
            stop=min([x for x in part['indices']if first<x<p.MISSING]+[part['count']])
            for index in range(first,stop):
                struct.pack_into('<3f',output,part['keys']+index*part['stride']+4,*base[bone][1])
        return bytes(output)


def _one_handed_sources(references,read_original):
    """Find unsolved adapted clips, including when updating a frozen old pack."""
    ready=references['PISTOL','STAND'];original=p._original(ready)
    if not original.endswith('/dwagentmale_readystand_ub.sanm'):
        raise ValueError('Unrecognized one-handed motion source basis')
    prefix=ready[:-len(original)]
    tree=p.art.decode(read_original('characters/multiplayer/multiplayeranimation.bxml'))
    result={}
    for group in tree['children']:
        name=group['attributes'].get('ToolName')
        if name not in('Movement UB Pistol','Crouch Movement Pistol'):continue
        for node in group['children']:
            key=_motion_key(name,node)
            if key in result:raise ValueError('Ambiguous one-handed source motion')
            flags={c['attributes']['Flag']for c in node['children']if c['name']=='Modifier'}
            if not {'PISTOL','REVOLVER','OUT_OF_VEHICLE'}<=flags:
                raise ValueError('Unsupported one-handed source motion')
            result[key]=prefix+p.art.norm(node['attributes']['Name'])+'.sanm'
    if len(result)!=14:raise ValueError('Incomplete one-handed source motion')
    return result


def _motion_key(group,node):
    attributes=node['attributes']
    return(group,attributes['AnimationID'],attributes.get('LocomotionMinRate'),
           attributes.get('LocomotionMaxRate')if not group.startswith('Crouch ')else None)


class ShotgunSupport(p.SupportRetarget):
    arm_bones=(18,19,20)

    def __init__(self,*args,right_offset=0.,**kwargs):
        super().__init__(*args,**kwargs)
        # Measured palm-up frame underneath the original shotgun fore-end.
        # Apply it in bind space so gloves and the added body rigs agree.
        frame=((-.302737528,-.092976450,.948527886),
               (.003112172,-.995321281,-.096570351),
               (.953068650,-.026283532,.301611273))
        self.contact_rotation=p.a._multiply(p.world(self.target,self.parents)[20][0],frame)
        points=[]
        model=args[1]
        for index in range(sum(kind==15 for kind,*_ in p.b._records(model))):
            geometry=skin._geometry(model,index,allowed_bones=(self.bones,))
            inverse=geometry['inverse'][20]
            for position,weights in zip(geometry['positions'],geometry['weights']):
                if weights.get(20,0.)+weights.get(21,0.)<=.5:continue
                local=tuple(sum(position[j]*inverse[j*4+i]for j in range(3))+inverse[12+i]for i in range(3))
                if .03<local[0]<.09:points.append(local)
        if not points:raise ValueError('Shotgun support palm is unavailable')
        center=tuple(sum(point[i]for point in points)/len(points)for i in range(3))
        self.contact_position=p.sub((.25,.055,-.05),p.rotate(center,self.contact_rotation))
        self.contact_grip=self.target_grip[0],p.add(self.target_grip[1],p.scale(self.target_grip[0][0],right_offset))

    def shift_grip(self,local,new_offset,old_offset=0.):
        before=p.world(local,self.parents);after=dict(before)
        desired=p.mul((self.contact_rotation,self.contact_position),p.mul(self.contact_grip,before[16]))
        shoulder,elbow,wrist=(before[b][1]for b in(18,19,20))
        middle,endpoint=p.solve(shoulder,elbow,wrist,desired[1])
        after[18]=p.a._multiply(before[18][0],p.align(p.sub(elbow,shoulder),p.sub(middle,shoulder))),shoulder
        after[19]=p.a._multiply(before[19][0],p.align(p.sub(wrist,elbow),p.sub(endpoint,middle))),middle
        after[20]=desired[0],endpoint
        after[21]=p.mul(p.mul(before[21],p.inverse(before[20])),after[20])
        after=p.world(p.outside_elbow(p.localize(after,self.parents),self.parents,18,forward_weight=1.),self.parents)
        # Roll the humerus toward the natural underhand bend plane. Joint
        # positions, forearm/hand orientation and the complete gun stay fixed.
        axis=p.unit(p.sub(after[19][1],shoulder));half=math.pi/12
        roll=p.a._quaternion_matrix((*p.scale(axis,math.sin(half)),math.cos(half)))
        rotation=p.a._multiply(before[18][0],p.align(p.sub(elbow,shoulder),p.sub(after[19][1],shoulder)))
        after[18]=p.a._multiply(rotation,roll),shoulder
        after[19]=p.a._multiply(before[19][0],p.align(p.sub(wrist,elbow),p.sub(endpoint,after[19][1]))),after[19][1]
        return p.localize(after,self.parents)

    def bake_support(self,data,reference=None,*,native_aim=False):
        # Reuse the existing absolute/additive contact encoder. This is a
        # complete support pose, not an additional weapon attachment offset.
        if native_aim:
            # The native full-right pose carries the elbow around the chest.
            # Fade out the underhand adjustment toward that authored endpoint.
            target=p.Clip(data,self.bones,True)
            if reference is None or not target.flags&0x10000000:raise ValueError('Expected Shotgun aim reference')
            base=p.Clip(reference,self.bones).pose(self.target,.5)
            corrected=self.shift_grip(base,1.)
            neutral={bone:(p.a.IDENTITY,(0.,0.,0.))for bone in base}
            def sample(phase):
                delta=target.pose(neutral,phase)
                return {bone:(p.a._multiply(p.a._inverse(corrected[bone][0]),p.a._multiply(base[bone][0],delta[bone][0])),
                              delta[bone][1])for bone in base}
            phases={0.,1.}
            for times,_ in target.tracks.values():phases.update(times)
            return self._encode_rotations(target,sample,phases)
        return self.bake_grip(data,1.)if reference is None else self.bake_grip_delta(reference,data,1.)


def _prepare_shotgun_support(raw,read,read_original,model,locator,basis,actor,offsets):
    if actor not in p.GRIP_ACTORS:raise ValueError('Unsupported Shotgun support actor')
    # The original glove rigs already cradle this fore-end. Their larger
    # fingers must keep that authored contact instead of the slimmer-hand fit.
    if actor in {'Chaz','JerichoCoop','CivilianJerichoSolo','CivilianJerichoCoop',
                 'TrooperSolo','TrooperCoop','BlueTrooperSolo','BlueTrooperCoop','RedTrooperSolo','RedTrooperCoop'}:
        return raw,{}
    tree=p.art.decode(raw);rows=[];references={};prefix=PREFIX+'support-under/'
    for group in tree['children']:
        name=group['attributes'].get('ToolName')
        if name not in('Alert Poses UB','Crouch Alert Poses','Shotgun Aim','Weapon Shoot'):continue
        for node in group['children']:
            if node['name']!='KeyframeAnimation':continue
            flags={c['attributes']['Flag']for c in node['children']if c['name']=='Modifier'}
            if 'SHOTGUN'not in flags:continue
            if flags&p.WEAPONS!={'SHOTGUN'}:raise ValueError('Mixed Shotgun support selector')
            stance='CROUCH'if'CROUCH'in flags else'STAND'
            path=p.art.norm(node['attributes']['Name'])+'.sanm';rows.append((node,path,stance))
            if name in('Alert Poses UB','Crouch Alert Poses'):
                if stance in references:raise ValueError('Duplicate Shotgun support reference')
                references[stance]=path
    if set(references)!={'STAND','CROUCH'}:raise ValueError('Missing Shotgun support references')
    if all(path.startswith(prefix)for path in references.values()):return raw,{}
    data={stance:read(path)for stance,path in references.items()};bones=struct.unpack_from('<I',data['STAND'],8)[0]
    source_locator=basis[:-4]+('_coop.bllist'if basis==p.a.STORM else'.bllist')
    solver=ShotgunSupport(read_original(basis),model,p._grip(read_original(source_locator)),p._grip(locator),bones,
                         right_offset=offsets.get((actor,'Shotgun'),(0.,0.))[0])
    additions={};cache={}
    for node,path,stance in rows:
        native_aim=node['attributes'].get('AnimationID')=='AIM_POSE_RIGHT'
        key=path,stance,native_aim
        if key not in cache:
            original=read(path)
            output=solver.bake_support(original,data[stance]if struct.unpack_from('<I',original,20)[0]&0x10000000 else None,
                                      native_aim=native_aim)
            name=prefix+hashlib.sha256(output).hexdigest()[:24];cache[key]=name;additions[name+'.sanm']=output
        node['attributes']['Name']=cache[key]
    return p.art.encode(tree),additions


# Minimum measured rifle-stock clearance for the native crouched rigs.
RIFLE_CROUCH_CLEARANCE = {
    'Chaz': (0.06, 0.0),
    'JerichoCoop': (0.06, 0.0),
    'CivilianJerichoSolo': (0.06, 0.0),
    'TrooperSolo': (0.06, 0.0),
    'BlueTrooperSolo': (0.06, 0.0),
    'RedTrooperSolo': (0.06, 0.0),
    'CassidySpectralSolo': (0.1, 0.0),
    'TalaSolo': (0.1, 0.0),
    'VampireTalaSolo': (0.1, 0.0),
    'CivilianJerichoCoop': (0.1, 0.0),
    'CassidyPlayerTwo': (0.06, 0.04),
    'CassidySpectralPlayerTwo': (0.06, 0.04),
    'TalaCoop': (0.06, 0.04),
    'TrooperCoop': (0.02, 0.04),
    'BlueTrooperCoop': (0.02, 0.04),
    'RedTrooperCoop': (0.02, 0.04),
}


class RifleClearance(p.SupportRetarget):
    arm_bones = HOLD_BONES

    def shift_grip(self, local, new_offset, old_offset=0.):
        before = p.world(local, self.parents)
        gun = p.mul(self.target_grip, before[16])
        delta = p.add(p.scale(gun[0][2], self.clearance[0]), (0., self.clearance[1], 0.))
        # Extreme aim may already use the whole arm. Move the paired contacts
        # only as far as both native-length chains can reach.
        amount = 1.
        for first in (13, 18):
            shoulder, elbow, wrist = (before[b][1] for b in (first, first+1, first+2))
            radius = p.length(p.sub(elbow, shoulder)) + p.length(p.sub(wrist, elbow)) - 1e-6
            offset = p.sub(wrist, shoulder); square = p.dot(delta, delta)
            dot = p.dot(offset, delta)
            bound = (-dot + math.sqrt(max(0., dot*dot-square*(p.dot(offset, offset)-radius*radius)))) / square
            amount = min(amount, max(0., bound))
        delta = p.scale(delta, amount)
        after = dict(before)
        for first in (13, 18):
            shoulder, elbow, wrist = (before[b][1] for b in (first, first+1, first+2))
            middle, endpoint = p.solve(shoulder, elbow, wrist, p.add(wrist, delta))
            after[first] = p.a._multiply(before[first][0], p.align(p.sub(elbow, shoulder), p.sub(middle, shoulder))), shoulder
            after[first+1] = p.a._multiply(before[first+1][0], p.align(p.sub(wrist, elbow), p.sub(endpoint, middle))), middle
            after[first+2] = before[first+2][0], endpoint
            after[first+3] = p.mul(local[first+3], after[first+2])
        return p.localize(after, self.parents)


def _prepare_rifle_clearance(raw, read, read_original, model, locator, basis, actor):
    if actor not in RIFLE_CROUCH_CLEARANCE:
        return raw, {}
    tree = p.art.decode(raw); selected = []; reference = None
    prefix = PREFIX + 'rifle-clearance/'
    for group in tree['children']:
        kind = group['attributes'].get('ToolName')
        if kind not in ('Crouch Alert Poses', 'Rifle Aim', 'Weapon Shoot'):
            continue
        for node in group['children']:
            if node['name'] != 'KeyframeAnimation': continue
            flags = {c['attributes']['Flag'] for c in node['children'] if c['name'] == 'Modifier'}
            if not {'RIFLE', 'CROUCH'} <= flags: continue
            path = p.art.norm(node['attributes']['Name']) + '.sanm'
            selected.append((group, node, path, flags))
            if kind == 'Crouch Alert Poses':
                if reference is not None: raise ValueError('Duplicate crouched rifle ready')
                reference = path
    if reference is None: raise ValueError('Missing crouched rifle ready')
    if reference.startswith(prefix): return raw, {}
    data = read(reference); bones = struct.unpack_from('<I', data, 8)[0]
    source_locator = basis[:-4] + ('_coop.bllist' if basis == p.a.STORM else '.bllist')
    solver = RifleClearance(read_original(basis), model, p._grip(read_original(source_locator)), p._grip(locator), bones)
    solver.clearance = RIFLE_CROUCH_CLEARANCE[actor]
    additions = {}; cache = {}
    for group, node, path, flags in selected:
        if path not in cache:
            original = read(path)
            output = (solver.bake_grip_delta(data, original, 1.) if struct.unpack_from('<I', original, 20)[0] & 0x10000000
                      else solver.bake_grip(original, 1.))
            name = prefix + hashlib.sha256(output).hexdigest()[:24]
            cache[path] = name; additions[name + '.sanm'] = output
        replacement = copy.deepcopy(node); replacement['attributes']['Name'] = cache[path]
        replacement['children'] = [c for c in replacement['children'] if not (c['name'] == 'Modifier' and c['attributes']['Flag'] in p.WEAPONS-{'RIFLE'})]
        index = next(i for i, entry in enumerate(group['children']) if entry is node)
        replacements = [replacement]
        if flags & (p.WEAPONS-{'RIFLE'}):
            node['children'] = [c for c in node['children'] if not(c['name'] == 'Modifier' and c['attributes']['Flag'] == 'RIFLE')]
            replacements.insert(0, node)
        group['children'][index:index+1] = replacements
        group['attributes']['KeyedAnimationCount'] = str(sum(n['name'] == 'KeyframeAnimation' for n in group['children']))
    return p.art.encode(tree), additions


def prepare_aimed_motion_table(raw,read,read_original,model,locator,basis,actor,offsets):
    """Share ready aim through directional and jump blends; keep native legs."""
    if actor not in p.GRIP_ACTORS or basis not in(p.a.CHAZ,p.a.STORM):
        raise ValueError('Unsupported aimed-motion body rig')
    raw,adjusted=shoulder.prepare_table(raw,read,read_original,model,locator,basis,actor,offsets)
    previous=read
    read=lambda path:adjusted[path]if path in adjusted else previous(path)
    raw,support=_prepare_shotgun_support(raw,read,read_original,model,locator,basis,actor,offsets)
    adjusted.update(support)
    raw,rifle=_prepare_rifle_clearance(raw,read,read_original,model,locator,basis,actor)
    adjusted.update(rifle)
    tree=p.art.decode(raw);references={}
    for group in tree['children']:
        name=group['attributes'].get('ToolName')
        if name not in('Alert Poses UB','Crouch Alert Poses'):continue
        stance='CROUCH'if name=='Crouch Alert Poses'else'STAND'
        for node in group['children']:
            if node['name']!='KeyframeAnimation' or node['attributes'].get('AnimationID')!='IDLE':continue
            flags={c['attributes']['Flag']for c in node['children']if c['name']=='Modifier'}
            for flag in flags&p.WEAPONS:
                key=flag,stance
                if key in references:raise ValueError('Duplicate aimed-motion ready reference')
                references[key]=p.art.norm(node['attributes']['Name'])+'.sanm'
    weapons=dict(PISTOL='BasicPistol',REVOLVER='Revolver',DOUBLEPISTOL='DoublePistol',RIFLE='Rifle',
                 SNIPERRIFLE='SniperRifle',CROSSBOW='Crossbow',SHOTGUN='Shotgun',RAILRCKT='RocketLauncher')
    if set(references)!={(flag,stance)for flag in weapons for stance in('STAND','CROUCH')}:
        raise ValueError('Incomplete aimed-motion weapon references')
    first=read(next(iter(references.values())));bones=struct.unpack_from('<I',first,8)[0]
    source_locator=basis[:-4]+('_coop.bllist'if basis==p.a.STORM else'.bllist')
    solver=AimedMotion(read_original(basis),model,p._grip(read_original(source_locator)),p._grip(locator),bones)
    free_sources=_one_handed_sources(references,read_original)
    additions=dict(adjusted);cache={};found=set()
    for group in tree['children']:
        name=group['attributes'].get('ToolName','')
        if not name.startswith(('Jump ','Vampire Jump ','Movement UB ','Crouch Movement ')):continue
        if name.endswith((' Flag',' Core')):continue
        rows=[]
        for node in group['children']:
            if node['name']!='KeyframeAnimation':raise ValueError('Unexpected aimed-motion action')
            flags={c['attributes']['Flag']for c in node['children']if c['name']=='Modifier'}
            selected=flags&weapons.keys()
            if not selected or 'OUT_OF_VEHICLE'not in flags:raise ValueError('Unsupported aimed-motion selector')
            stance='CROUCH'if'CROUCH'in flags else'STAND'
            path=p.art.norm(node['attributes']['Name'])+'.sanm'
            for flag in sorted(selected):
                free_arm=flag in('PISTOL','REVOLVER')and name in('Movement UB Pistol','Crouch Movement Pistol')
                source=free_sources[_motion_key(name,node)]if free_arm else path
                key=source,flag,stance,free_arm
                if key not in cache:
                    clip=solver.bake_motion(read(source),read(references[flag,stance]),free_arm=free_arm)
                    destination=PREFIX+'motion/'+hashlib.sha256(clip).hexdigest()[:24]
                    cache[key]=destination;additions[destination+'.sanm']=clip
                replacement=copy.deepcopy(node);replacement['attributes']['Name']=cache[key]
                # The core crouch loop has no speed ceiling. Keep its armed
                # upper body present while the incoming run speed decelerates.
                if name.startswith('Crouch Movement ')and node['attributes']['AnimationID']=='LOCO_FORWARD':
                    replacement['attributes'].pop('LocomotionMaxRate',None)
                replacement['children']=[c for c in replacement['children']if not(c['name']=='Modifier'and c['attributes']['Flag']in selected-{flag})]
                rows.append(replacement);found.add(flag)
        group['children']=rows;group['attributes']['KeyedAnimationCount']=str(len(rows))
    if found!=set(weapons):raise ValueError('Incomplete aimed-motion weapon coverage')
    return p.art.encode(tree),additions
