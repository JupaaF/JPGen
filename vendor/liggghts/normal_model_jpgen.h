// JPGen LIGGGHTS extension, GPL-2.0-or-later.
#ifdef NORMAL_MODEL
NORMAL_MODEL(JPGEN_HERTZ,jpgen_hertz,15)
#else
#ifndef JPGEN_NORMAL_H
#define JPGEN_NORMAL_H
#include "normal_model_base.h"
#include "global_properties.h"
#include <cmath>
namespace LIGGGHTS { namespace ContactModels {
template<> class NormalModel<JPGEN_HERTZ> : public NormalModelBase {
  double **young, **shear, **rest;
public:
  NormalModel(LAMMPS *lmp,IContactHistorySetup *h,ContactModelBase *c)
    : NormalModelBase(lmp,h,c),young(0),shear(0),rest(0) {}
  void registerSettings(Settings&) {}
  void postSettings(IContactHistorySetup*,ContactModelBase*) {}
  void connectToProperties(PropertyRegistry &r) {
    // JPGen validates -1 < nu < 0.5 and 0 <= restitution <= 1.
    // Register before effective-modulus factories impose upstream restrictions.
    r.registerProperty("poissonsRatio",&MODEL_PARAMS::createPoissonsRatio,false);
    r.registerProperty("Yeff",&MODEL_PARAMS::createYeff);
    r.registerProperty("Geff",&MODEL_PARAMS::createGeff);
    r.registerProperty("coefficientRestitution",&MODEL_PARAMS::createCoeffRest,false);
    r.connect("Yeff",young,"jpgen_hertz");
    r.connect("Geff",shear,"jpgen_hertz");
    r.connect("coefficientRestitution",rest,"jpgen_hertz");
  }
  double stressStrainExponent() { return 1.5; }
  void surfacesIntersect(SurfacesIntersectData &s,ForceData &i,ForceData &j) {
    if(s.contact_flags) *s.contact_flags |= CONTACT_NORMAL_MODEL;
    const double reff=s.radi*s.radj/(s.radi+s.radj);
    const double q=std::sqrt(reff*s.deltan);
    const double Sn=2*young[s.itype][s.jtype]*q;
    s.kn=Sn*2/3; s.kt=8*shear[s.itype][s.jtype]*q;
    const double e=std::fmax(0.001,rest[s.itype][s.jtype]);
    // Thornton restitution fit used by Kratos GammaForHertzThornton.
    const double alpha=e*(-6.918798+e*(-16.41105+e*(146.8049+e*(-796.4559+
      e*(2928.711+e*(-7206.864+e*(11494.29+e*(-11342.18+e*(6276.757-e*1489.915)))))))));
    const double gamma=e>0.999 ? 0 : std::sqrt(1/(1-(1+e)*(1+e)*std::exp(alpha))-1);
    s.gamman=2*gamma*std::sqrt(s.meff*Sn);
    s.gammat=2*gamma*std::sqrt(s.meff*s.kt);
    s.Fn=std::fmax(0.0,s.kn*s.deltan-s.gamman*s.vn);
    for(int a=0;a<3;++a) { i.delta_F[a]+=s.Fn*s.en[a]; j.delta_F[a]-=s.Fn*s.en[a]; }
  }
  void surfacesClose(SurfacesCloseData&,ForceData&,ForceData&) {}
  void beginPass(SurfacesIntersectData&,ForceData&,ForceData&) {}
  void endPass(SurfacesIntersectData&,ForceData&,ForceData&) {}
};
}}
#endif
#endif
