// JPGen LIGGGHTS extension, GPL-2.0-or-later.
#include "fix_jpgen_sphere.h"
#include "atom.h"
#include "neighbor.h"
#include "error.h"
#include <cmath>
using namespace LAMMPS_NS;
void FixJPGenSphere::final_integrate() {
  // Forces at x_n,v_n; kick then drift (symplectic Euler, solid-sphere inertia).
  int invalid=0;
  const double limit=0.5*neighbor->skin;
  #pragma omp parallel for schedule(static) reduction(|:invalid) if(atom->nlocal >= 256)
  for (int i=0;i<atom->nlocal;++i) if (atom->mask[i]&groupbit) {
    for (int a=0;a<3;++a) {
      atom->v[i][a] += 2*dtf*atom->f[i][a]/atom->rmass[i];
      atom->omega[i][a] += 2*dtf*atom->torque[i][a]/
        (0.4*atom->rmass[i]*atom->radius[i]*atom->radius[i]);
      atom->x[i][a] += dtv*atom->v[i][a];
    }
    double displacement2=0;
    for (int a=0;a<3;++a) displacement2+=dtv*dtv*atom->v[i][a]*atom->v[i][a];
    if (!std::isfinite(displacement2) || displacement2>=limit*limit) invalid=1;
  }
  // Completed-step observations reuse the list built before the drift. Two
  // centers moving less than half the skin cannot create an unlisted contact.
  if (invalid) error->all(FLERR,"JPGen displacement exceeds half the neighbor skin; reduce time_step");
}
