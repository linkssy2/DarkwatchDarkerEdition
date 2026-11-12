#pragma once
#include <array>
#include <algorithm>
#include <cmath>

namespace darkwatch::clips {
using Vec = std::array<float,3>;
inline Vec Add(Vec a,Vec b){for(unsigned i=0;i<3;++i)a[i]+=b[i];return a;}
inline Vec Scale(Vec a,float s){for(auto& x:a)x*=s;return a;}
inline Vec Sub(Vec a,Vec b){return Add(a,Scale(b,-1));}
inline float Dot(Vec a,Vec b){return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
inline Vec Cross(Vec a,Vec b){return {a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]};}
struct FootBox {Vec center;std::array<Vec,3> axes;Vec half;};
inline float Radius(const FootBox& b,Vec n){float r=0;for(unsigned i=0;i<3;++i)r+=b.half[i]*std::abs(Dot(b.axes[i],n));return r;}
// Continuous separating-axis test: no center-radius proximity kicks.
inline bool SweepFoot(const FootBox& foot,Vec previous,const FootBox& clip,float& time,Vec& normal){
 const Vec start=Sub(previous,clip.center),travel=Sub(foot.center,previous);
 float enter=0,leave=1;Vec hit{};float penetration=INFINITY;Vec overlap{};
 auto axis=[&](Vec n){
  const float length=std::sqrt(Dot(n,n));if(length<1e-5f)return true;n=Scale(n,1/length);
  const float radius=Radius(foot,n)+Radius(clip,n),s=Dot(start,n),speed=Dot(travel,n);
  const float depth=radius-std::abs(s);if(depth<penetration){penetration=depth;overlap=Scale(n,s>0?-1.f:1.f);}
  if(std::abs(speed)<1e-7f)return std::abs(s)<=radius;
  float a=(-radius-s)/speed,b=(radius-s)/speed;if(a>b)std::swap(a,b);
  if(a>enter){enter=a;hit=Scale(n,speed>0?1.f:-1.f);}leave=std::min(leave,b);return enter<=leave;
 };
 for(auto n:foot.axes)if(!axis(n))return false;
 for(auto n:clip.axes)if(!axis(n))return false;
 for(auto a:foot.axes)for(auto b:clip.axes)if(!axis(Cross(a,b)))return false;
 if(leave<0||enter>1)return false;time=enter;normal=enter>0?hit:overlap;return true;
}
inline Vec Closest(const FootBox& box,Vec point){
 Vec result=box.center,d=Sub(point,box.center);
 for(unsigned i=0;i<3;++i)result=Add(result,Scale(box.axes[i],std::clamp(Dot(d,box.axes[i]),-box.half[i],box.half[i])));
 return result;
}
// Infinite-mass animated foot, finite native clip: no reaction on the player.
inline Vec FootImpulse(Vec velocity,Vec linear,Vec angular,Vec arm,Vec normal,float inverseMass,const std::array<Vec,3>& inverseInertia){
 const float closing=Dot(Sub(velocity,Add(linear,Cross(angular,arm))),normal);
 if(!(closing>0)||!(inverseMass>0))return {};
 const Vec torque=Cross(arm,normal);Vec spin{};
 for(unsigned i=0;i<3;++i)spin[i]=Dot(inverseInertia[i],torque);
 const float effective=inverseMass+Dot(torque,spin);
 if(!(effective>0)||!std::isfinite(effective))return {};
 return Scale(normal,closing/effective);
}
}
