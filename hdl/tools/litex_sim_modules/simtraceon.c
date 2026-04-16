#include <stdlib.h>
#include <string.h>

#include "error.h"
#include "modules.h"

struct session_s {
  char *trace;
};

static int litex_sim_module_pads_get(struct pad_s *pads, char *name, void **signal)
{
  int ret = RC_OK;
  void *sig = NULL;
  int i;

  if (!pads || !name || !signal) {
    ret = RC_INVARG;
    goto out;
  }

  i = 0;
  while (pads[i].name) {
    if (!strcmp(pads[i].name, name)) {
      sig = (void *)pads[i].signal;
      break;
    }
    i++;
  }

out:
  *signal = sig;
  return ret;
}

static int simtraceon_start(void *base)
{
  (void)base;
  return RC_OK;
}

static int simtraceon_new(void **sess, char *args)
{
  struct session_s *s;

  (void)args;
  if (!sess) {
    return RC_INVARG;
  }
  s = (struct session_s *)malloc(sizeof(struct session_s));
  if (!s) {
    return RC_NOENMEM;
  }
  memset(s, 0, sizeof(struct session_s));
  *sess = (void *)s;
  return RC_OK;
}

static int simtraceon_add_pads(void *sess, struct pad_list_s *plist)
{
  struct session_s *s = (struct session_s *)sess;

  if (!sess || !plist) {
    return RC_INVARG;
  }
  if (strcmp(plist->name, "sim_trace")) {
    return RC_OK;
  }
  return litex_sim_module_pads_get(plist->pads, "sim_trace", (void **)&s->trace);
}

static int simtraceon_tick(void *sess, uint64_t time_ps)
{
  struct session_s *s = (struct session_s *)sess;

  (void)time_ps;
  if (!s || !s->trace) {
    return RC_INVARG;
  }
  *s->trace = 1;
  return RC_OK;
}

static struct ext_module_s ext_mod = {
  "simtraceon",
  simtraceon_start,
  simtraceon_new,
  simtraceon_add_pads,
  NULL,
  simtraceon_tick
};

int litex_sim_ext_module_init(int (*register_module)(struct ext_module_s *))
{
  return register_module(&ext_mod);
}