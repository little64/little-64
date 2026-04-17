#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "error.h"
#include "modules.h"

#define SDCARD_IMAGE_FILENAME "sdcard.img"
#define SDCARD_BLOCK_SIZE 512
#define SDCARD_WORDS_PER_BLOCK (SDCARD_BLOCK_SIZE / 4)

struct session_s {
  uint8_t *sys_clk;
  uint8_t *req;
  uint32_t *byteaddr;
  uint8_t *write_addr;
  uint32_t *write_data;
  uint8_t *write_enable;
  uint8_t *done;
  clk_edge_state_t edge_state;
  FILE *image;
  uint32_t block_words[SDCARD_WORDS_PER_BLOCK];
  unsigned word_index;
  int serving_request;
  int request_seen;
  int warned_missing_image;
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

static void sdcardimage_open_if_needed(struct session_s *s)
{
  if (s->image != NULL) {
    return;
  }

  s->image = fopen(SDCARD_IMAGE_FILENAME, "rb");
  if (s->image == NULL && !s->warned_missing_image) {
    fprintf(stderr, "sdcardimage: unable to open %s\n", SDCARD_IMAGE_FILENAME);
    s->warned_missing_image = 1;
  }
}

static void sdcardimage_load_block(struct session_s *s, uint32_t byteaddr)
{
  uint8_t block_bytes[SDCARD_BLOCK_SIZE];
  size_t read_size = 0;
  unsigned i;

  memset(block_bytes, 0, sizeof(block_bytes));
  sdcardimage_open_if_needed(s);
  if (s->image != NULL) {
    if (fseek(s->image, (long)byteaddr, SEEK_SET) == 0) {
      read_size = fread(block_bytes, 1, sizeof(block_bytes), s->image);
    }
    if (read_size < sizeof(block_bytes) && ferror(s->image)) {
      clearerr(s->image);
    }
  }

  for (i = 0; i < SDCARD_WORDS_PER_BLOCK; ++i) {
    unsigned offset = i * 4;
    s->block_words[i] =
      ((uint32_t)block_bytes[offset + 0] << 24) |
      ((uint32_t)block_bytes[offset + 1] << 16) |
      ((uint32_t)block_bytes[offset + 2] << 8) |
      (uint32_t)block_bytes[offset + 3];
  }
}

static int sdcardimage_start(void *base)
{
  (void)base;
  return RC_OK;
}

static int sdcardimage_new(void **sess, char *args)
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

static int sdcardimage_add_pads(void *sess, struct pad_list_s *plist)
{
  struct session_s *s = (struct session_s *)sess;

  if (!sess || !plist) {
    return RC_INVARG;
  }

  if (!strcmp(plist->name, "sdcard_img")) {
    litex_sim_module_pads_get(plist->pads, "req", (void **)&s->req);
    litex_sim_module_pads_get(plist->pads, "byteaddr", (void **)&s->byteaddr);
    litex_sim_module_pads_get(plist->pads, "write_addr", (void **)&s->write_addr);
    litex_sim_module_pads_get(plist->pads, "write_data", (void **)&s->write_data);
    litex_sim_module_pads_get(plist->pads, "write_enable", (void **)&s->write_enable);
    return litex_sim_module_pads_get(plist->pads, "done", (void **)&s->done);
  }

  if (!strcmp(plist->name, "sys_clk")) {
    return litex_sim_module_pads_get(plist->pads, "sys_clk", (void **)&s->sys_clk);
  }

  return RC_OK;
}

static int sdcardimage_close(void *sess)
{
  struct session_s *s = (struct session_s *)sess;

  if (!s) {
    return RC_INVARG;
  }
  if (s->image != NULL) {
    fclose(s->image);
  }
  free(s);
  return RC_OK;
}

static int sdcardimage_tick(void *sess, uint64_t time_ps)
{
  struct session_s *s = (struct session_s *)sess;

  (void)time_ps;
  if (!s || !s->sys_clk || !s->req || !s->byteaddr || !s->write_addr || !s->write_data || !s->write_enable || !s->done) {
    return RC_INVARG;
  }
  if (!clk_pos_edge(&s->edge_state, *s->sys_clk)) {
    return RC_OK;
  }

  *s->write_enable = 0;
  *s->done = 0;

  if (!*s->req) {
    s->request_seen = 0;
  }

  if (!s->serving_request && *s->req && !s->request_seen) {
    sdcardimage_load_block(s, *s->byteaddr);
    s->word_index = 0;
    s->serving_request = 1;
    s->request_seen = 1;
  }

  if (s->serving_request) {
    if (s->word_index < SDCARD_WORDS_PER_BLOCK) {
      *s->write_addr = (uint8_t)s->word_index;
      *s->write_data = s->block_words[s->word_index];
      *s->write_enable = 1;
      s->word_index++;
    } else {
      *s->done = 1;
      s->serving_request = 0;
    }
  }

  return RC_OK;
}

static struct ext_module_s ext_mod = {
  "sdcardimage",
  sdcardimage_start,
  sdcardimage_new,
  sdcardimage_add_pads,
  sdcardimage_close,
  sdcardimage_tick
};

int litex_sim_ext_module_init(int (*register_module)(struct ext_module_s *))
{
  return register_module(&ext_mod);
}