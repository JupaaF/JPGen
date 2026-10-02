// JPGen LIGGGHTS extension, GPL-2.0-or-later.
#include "fix_jpgen_sphere.h"
#include "atom.h"
using namespace LAMMPS_NS;
void FixJPGenSphere::final_integrate() {
  // Forces at x_n,v_n; kick then drift (symplectic Euler, solid-sphere inertia).
  #pragma omp parallel for schedule(static) if(atom->nlocal >= 256)
  for (int i=0;i<atom->nlocal;++i) if (atom->mask[i]&groupbit) {
    for (int a=0;a<3;++a) {
      atom->v[i][a] += 2*dtf*atom->f[i][a]/atom->rmass[i];
      atom->omega[i][a] += 2*dtf*atom->torque[i][a]/
        (0.4*atom->rmass[i]*atom->radius[i]*atom->radius[i]);
      atom->x[i][a] += dtv*atom->v[i][a];
    }
  }
}
