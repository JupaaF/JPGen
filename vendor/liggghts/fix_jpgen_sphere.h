// JPGen LIGGGHTS extension, GPL-2.0-or-later (see LICENSE in this directory).
#ifdef FIX_CLASS
FixStyle(jpgen/sphere,FixJPGenSphere)
#else
#ifndef JPGEN_SPHERE_H
#define JPGEN_SPHERE_H
#include "fix_nve_sphere.h"
namespace LAMMPS_NS {
class FixJPGenSphere : public FixNVESphere {
public:
  FixJPGenSphere(LAMMPS *lmp, int argc, char **argv) : FixNVESphere(lmp,argc,argv) {}
  void initial_integrate(int) {}
  void final_integrate();
};
}
#endif
#endif
