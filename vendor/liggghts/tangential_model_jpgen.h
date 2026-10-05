// JPGen LIGGGHTS extension, GPL-2.0-or-later.
#ifdef TANGENTIAL_MODEL
TANGENTIAL_MODEL(JPGEN_HISTORY,jpgen_history,15)
#else
#ifndef JPGEN_TANGENTIAL_H
#define JPGEN_TANGENTIAL_H
#include "tangential_model_base.h"
#include "global_properties.h"
#include <cmath>
namespace LIGGGHTS { namespace ContactModels {
template<> class TangentialModel<JPGEN_HISTORY> : public TangentialModelBase {
  double **friction, **dynamic_friction, **friction_decay;
  int offset;
public:
  TangentialModel(LAMMPS *lmp,IContactHistorySetup *h,ContactModelBase *c)
    : TangentialModelBase(lmp,h,c),friction(0),dynamic_friction(0),friction_decay(0) {
    offset=h->add_history_value("jpgen_elastic_x","1");
    h->add_history_value("jpgen_elastic_y","1");
    h->add_history_value("jpgen_elastic_z","1");
    h->add_history_value("jpgen_previous_overlap","0");
    h->add_history_value("jpgen_normal_x","1");
    h->add_history_value("jpgen_normal_y","1");
    h->add_history_value("jpgen_normal_z","1");
  }
  void registerSettings(Settings&) {}
  void postSettings(IContactHistorySetup*,ContactModelBase*) {}
  static MatrixProperty *createDynamicFriction(PropertyRegistry &r,const char *caller,bool) {
    return MODEL_PARAMS::createPerTypePairProperty(r,"jpgenDynamicFriction",caller);
  }
  static MatrixProperty *createFrictionDecay(PropertyRegistry &r,const char *caller,bool) {
    return MODEL_PARAMS::createPerTypePairProperty(r,"jpgenFrictionDecay",caller);
  }
  void connectToProperties(PropertyRegistry &r) {
    r.registerProperty("coeffFrict",&MODEL_PARAMS::createCoeffFrict);
    r.connect("coeffFrict",friction,"jpgen_history");
    r.registerProperty("jpgenDynamicFriction",&createDynamicFriction);
    r.registerProperty("jpgenFrictionDecay",&createFrictionDecay);
    r.connect("jpgenDynamicFriction",dynamic_friction,"jpgen_history");
    r.connect("jpgenFrictionDecay",friction_decay,"jpgen_history");
  }
  void surfacesIntersect(const SurfacesIntersectData &s,ForceData &i,ForceData &j) {
    if(s.computeflag && s.contact_flags) *s.contact_flags |= CONTACT_TANGENTIAL_MODEL;
    double *h=&s.contact_history[offset];
    double elastic[3], viscous[3], total[3];
    // Minimal rotation between the previous and current contact normals.
    // Rodrigues: R h = h + k x h + k x (k x h)/(1+c), k=n_old x n.
    const double *old=&h[4];
    double c=0, oldnormal2=0;
    for(int a=0;a<3;++a) { c+=old[a]*s.en[a]; oldnormal2+=old[a]*old[a]; }
    const double k[3]={old[1]*s.en[2]-old[2]*s.en[1],
      old[2]*s.en[0]-old[0]*s.en[2],old[0]*s.en[1]-old[1]*s.en[0]};
    const double cross[3]={k[1]*h[2]-k[2]*h[1],k[2]*h[0]-k[0]*h[2],k[0]*h[1]-k[1]*h[0]};
    const double twice[3]={k[1]*cross[2]-k[2]*cross[1],
      k[2]*cross[0]-k[0]*cross[2],k[0]*cross[1]-k[1]*cross[0]};
    for(int a=0;a<3;++a) elastic[a]=h[a];
    if(oldnormal2>0 && c>-1+1e-12)
      for(int a=0;a<3;++a) elastic[a]+=cross[a]+twice[a]/(1+c);
    else if(oldnormal2>0) {
      // At antiparallel normals the minimal axis is ambiguous. A tangential
      // history itself supplies an axis for the 180-degree rotation.
      // Such a reversal should normally break contact before this branch.
      for(int a=0;a<3;++a) elastic[a]=h[a];
    }
    double normal=0;
    for(int a=0;a<3;++a) normal+=elastic[a]*s.en[a];
    for(int a=0;a<3;++a) elastic[a]-=normal*s.en[a];
    const double scale=h[3]>s.deltan ? std::sqrt(s.deltan/h[3]) : 1;
    const double slip[3]={s.vtr1,s.vtr2,s.vtr3};
    const bool advance=s.computeflag && s.shearupdate;
    double enorm2=0,vnorm2=0,dot=0,tnorm2=0;
    for(int a=0;a<3;++a) {
      elastic[a]=elastic[a]*scale-(advance ? s.kt*slip[a]*update->dt : 0);
      viscous[a]=-s.gammat*slip[a];
      total[a]=elastic[a]+viscous[a];
      enorm2+=elastic[a]*elastic[a]; vnorm2+=viscous[a]*viscous[a];
      dot+=elastic[a]*viscous[a]; tnorm2+=total[a]*total[a];
    }
    const double speed=std::sqrt(slip[0]*slip[0]+slip[1]*slip[1]+slip[2]*slip[2]);
    const double mu_dynamic=dynamic_friction[s.itype][s.jtype];
    const double mu=mu_dynamic+(friction[s.itype][s.jtype]-mu_dynamic)*
      std::exp(-friction_decay[s.itype][s.jtype]*speed);
    const double limit=mu*s.Fn;
    const double en=std::sqrt(enorm2),vn=std::sqrt(vnorm2);
    if(std::sqrt(tnorm2)>limit) {
      double ef=1,vf=1;
      if(dot>=0) { if(en>limit) { ef=limit/en;vf=0; }
        else vf=vn>0 ? (limit-en)/vn : 0; }
      else { if(vn>=en) vf=vn>0 ? (limit+en)/vn : 0;
        else { ef=en>0 ? limit/en : 0;vf=0; } }
      for(int a=0;a<3;++a) { elastic[a]*=ef;viscous[a]*=vf;total[a]=elastic[a]+viscous[a]; }
    }
    if(advance) { for(int a=0;a<3;++a) { h[a]=elastic[a]; h[4+a]=s.en[a]; } h[3]=s.deltan; }
    double torque[3]={s.en[1]*total[2]-s.en[2]*total[1],
      s.en[2]*total[0]-s.en[0]*total[2],s.en[0]*total[1]-s.en[1]*total[0]};
    for(int a=0;a<3;++a) {
      i.delta_F[a]+=total[a];j.delta_F[a]-=total[a];
      i.delta_torque[a]-=s.cri*torque[a];j.delta_torque[a]-=s.crj*torque[a];
    }
  }
  void surfacesClose(SurfacesCloseData &s,ForceData&,ForceData&) {
    if(s.computeflag && s.shearupdate && s.contact_history)
      for(int a=0;a<7;++a) s.contact_history[offset+a]=0;
  }
  void beginPass(SurfacesIntersectData&,ForceData&,ForceData&) {}
  void endPass(SurfacesIntersectData&,ForceData&,ForceData&) {}
};
}}
#endif
#endif
