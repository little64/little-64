#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "error.h"
#include "modules.h"

struct session_s {
  char *data;
  char *strobe;
  char *sys_clk;
  clk_edge_state_t edge_state;
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

static int breadcrumbconsole_start(void *base)
{
  (void)base;
  return RC_OK;
}

static int breadcrumbconsole_new(void **sess, char *args)
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

static int breadcrumbconsole_add_pads(void *sess, struct pad_list_s *plist)
{
  struct session_s *s = (struct session_s *)sess;

  if (!sess || !plist) {
    return RC_INVARG;
  }

  if (!strcmp(plist->name, "breadcrumb")) {
    if (litex_sim_module_pads_get(plist->pads, "data", (void **)&s->data) != RC_OK) {
      return RC_ERROR;
    }
    return litex_sim_module_pads_get(plist->pads, "strobe", (void **)&s->strobe);
  }

  if (!strcmp(plist->name, "sys_clk")) {
    return litex_sim_module_pads_get(plist->pads, "sys_clk", (void **)&s->sys_clk);
  }

  return RC_OK;
}

static int breadcrumbconsole_tick(void *sess, uint64_t time_ps)
{
  struct session_s *s = (struct session_s *)sess;

  (void)time_ps;
  if (!s || !s->data || !s->strobe || !s->sys_clk) {
    return RC_INVARG;
  }
  if (!clk_pos_edge(&s->edge_state, *s->sys_clk)) {
    return RC_OK;
  }
  if (*s->strobe) {
    printf("%c", *s->data);
    fflush(stdout);
  }
  return RC_OK;
}

static struct ext_module_s ext_mod = {
  "breadcrumbconsole",
  breadcrumbconsole_start,
  breadcrumbconsole_new,
  breadcrumbconsole_add_pads,
  NULL,
  breadcrumbconsole_tick
};

int litex_sim_ext_module_init(int (*register_module)(struct ext_module_s *))
{
  return register_module(&ext_mod);
}