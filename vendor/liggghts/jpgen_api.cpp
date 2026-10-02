// JPGen LIGGGHTS extension, GPL-2.0-or-later.
#include "lammps.h"
#include "modify.h"
#include "compute.h"
#include "atom.h"
#include "domain.h"
#include "comm.h"
#include "update.h"
#include "integrate.h"
#include "output.h"
#include "error.h"
#include "version_liggghts.h"
#include <omp.h>
extern "C" int jpgen_liggghts_api_version() { return 4; }
extern "C" void jpgen_liggghts_advance(void *handle) {
  LAMMPS_NS::LAMMPS *lmp=static_cast<LAMMPS_NS::LAMMPS*>(handle);
  LAMMPS_NS::Update *u=lmp->update;
  // The case's initial run 0 has initialized the live integrator and fixes.
  // Avoid Run::command's per-step thermo setup and Finish output. Keep every
  // Verlet callback, neighbor reconstruction and force/history update.
  if (!u->first_update || !u->integrate)
    lmp->error->all(FLERR,"JPGen advance requires an initialized run");
  u->whichflag=1;
  u->nsteps=1;
  u->beginstep=u->firststep=u->ntimestep;
  u->endstep=u->laststep=u->ntimestep+1;
  lmp->output->next=u->laststep+1;
  u->integrate->run(1);
  u->update_time();
  u->whichflag=0;
}
extern "C" void jpgen_liggghts_set_threads(int count) {
  omp_set_dynamic(0); omp_set_num_threads(count);
}
extern "C" int jpgen_liggghts_threads() {
  int count=1;
  #pragma omp parallel
  {
    #pragma omp single
    count=omp_get_num_threads();
  }
  return count;
}
extern "C" const char *jpgen_liggghts_version() { return LIGGGHTS_VERSION; }
extern "C" int jpgen_liggghts_contact_rows(void *handle) {
  LAMMPS_NS::LAMMPS *lmp=static_cast<LAMMPS_NS::LAMMPS*>(handle);
  const int index=lmp->modify->find_compute("jpgen_contacts");
  return index<0 ? -1 : lmp->modify->compute[index]->size_local_rows;
}
extern "C" void jpgen_liggghts_set_cell(void *handle, const double *origin, const double *lengths) {
  LAMMPS_NS::LAMMPS *lmp=static_cast<LAMMPS_NS::LAMMPS*>(handle);
  LAMMPS_NS::Domain *d=lmp->domain;
  // Do not migrate atoms here. Verlet's pre_exchange must first archive the
  // live pair history, then perform periodic wrapping and particle exchange.
  for(int a=0;a<3;++a) {
    const double scale=lengths[a]/(d->boxhi[a]-d->boxlo[a]);
    #pragma omp parallel for schedule(static) if(lmp->atom->nlocal >= 256)
    for(int i=0;i<lmp->atom->nlocal;++i)
      lmp->atom->x[i][a]=origin[a]+(lmp->atom->x[i][a]-d->boxlo[a])*scale;
    d->boxlo[a]=origin[a]; d->boxhi[a]=origin[a]+lengths[a];
  }
  d->set_global_box(); d->set_local_box(); d->box_change=1;
}
extern "C" void jpgen_liggghts_refresh_ghosts(void *handle) {
  static_cast<LAMMPS_NS::LAMMPS*>(handle)->comm->forward_comm();
}
