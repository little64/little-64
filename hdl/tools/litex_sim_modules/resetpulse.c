#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "error.h"
#include "modules.h"

#define RESET_HOLD_PS 5000000ull

struct session_s {
  char *rst;
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

static int resetpulse_start(void *base)
{
  (void)base;
  return RC_OK;
}

static int resetpulse_new(void **sess, char *args)
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

static int resetpulse_add_pads(void *sess, struct pad_list_s *plist)
{
  struct session_s *s = (struct session_s *)sess;

  if (!sess || !plist) {
    return RC_INVARG;
  }
  if (strcmp(plist->name, "sys_rst")) {
    return RC_OK;
  }

  return litex_sim_module_pads_get(plist->pads, "sys_rst", (void **)&s->rst);
}

static int resetpulse_tick(void *sess, uint64_t time_ps)
{
  struct session_s *s = (struct session_s *)sess;

  if (!s || !s->rst) {
    return RC_INVARG;
  }

  *s->rst = time_ps < RESET_HOLD_PS ? 1 : 0;
  return RC_OK;
}

static struct ext_module_s ext_mod = {
  "resetpulse",
  resetpulse_start,
  resetpulse_new,
  resetpulse_add_pads,
  NULL,
  resetpulse_tick
};

int litex_sim_ext_module_init(int (*register_module)(struct ext_module_s *))
{
  return register_module(&ext_mod);
}