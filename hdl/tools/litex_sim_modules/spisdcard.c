#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "error.h"
#include "modules.h"

#define SPI_SDCARD_IMAGE_FILENAME "sdcard.img"
#define SPI_SDCARD_BLOCK_SIZE 512U
#define SPI_SDCARD_QUEUE_SIZE 2048U

struct session_s {
  uint8_t *sys_clk;
  uint8_t *clk;
  uint8_t *mosi;
  uint8_t *miso;
  uint8_t *cs_n;
  clk_edge_state_t sys_edge;
  clk_edge_state_t spi_edge;
  FILE *image;
  uint8_t warned_missing_image;

  uint8_t selected;
  uint8_t cmd_len;
  uint8_t cmd_frame[6];
  uint8_t rx_byte;
  uint8_t rx_bits;

  uint8_t tx_queue[SPI_SDCARD_QUEUE_SIZE];
  unsigned tx_head;
  unsigned tx_tail;
  uint8_t tx_byte;
  uint8_t tx_bit_index;
  uint8_t tx_loaded;

  uint8_t acmd_pending;
  uint8_t initialized;
  uint8_t uses_block_addressing;
  uint8_t pending_multiblock_poll;
  uint8_t multiblock_active;
  uint32_t multiblock_next_block;
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

static void spisdcard_open_if_needed(struct session_s *s)
{
  if (s->image != NULL) {
    return;
  }

  s->image = fopen(SPI_SDCARD_IMAGE_FILENAME, "rb");
  if (s->image == NULL && !s->warned_missing_image) {
    fprintf(stderr, "spisdcard: unable to open %s\n", SPI_SDCARD_IMAGE_FILENAME);
    s->warned_missing_image = 1;
  }
}

static void spisdcard_reset_selection(struct session_s *s)
{
  s->selected = 0;
  s->cmd_len = 0;
  s->rx_byte = 0;
  s->rx_bits = 0;
  s->pending_multiblock_poll = 0;
  s->tx_loaded = 0;
  s->tx_bit_index = 0;
  if (s->miso != NULL) {
    *s->miso = 1;
  }
}

static unsigned spisdcard_queue_count(const struct session_s *s)
{
  return (s->tx_tail + SPI_SDCARD_QUEUE_SIZE - s->tx_head) % SPI_SDCARD_QUEUE_SIZE;
}

static void spisdcard_queue_byte(struct session_s *s, uint8_t value)
{
  unsigned next_tail = (s->tx_tail + 1U) % SPI_SDCARD_QUEUE_SIZE;
  if (next_tail == s->tx_head) {
    return;
  }
  s->tx_queue[s->tx_tail] = value;
  s->tx_tail = next_tail;
}

static uint8_t spisdcard_pop_byte(struct session_s *s, uint8_t *have_byte)
{
  uint8_t value = 0xFFU;

  if (s->tx_head == s->tx_tail) {
    *have_byte = 0;
    return value;
  }

  value = s->tx_queue[s->tx_head];
  s->tx_head = (s->tx_head + 1U) % SPI_SDCARD_QUEUE_SIZE;
  *have_byte = 1;
  return value;
}

static void spisdcard_load_block(uint32_t block_index, uint8_t *block_bytes, struct session_s *s)
{
  size_t read_size = 0;

  memset(block_bytes, 0, SPI_SDCARD_BLOCK_SIZE);
  spisdcard_open_if_needed(s);
  if (s->image != NULL) {
    if (fseek(s->image, (long)(block_index * SPI_SDCARD_BLOCK_SIZE), SEEK_SET) == 0) {
      read_size = fread(block_bytes, 1, SPI_SDCARD_BLOCK_SIZE, s->image);
    }
    if (read_size < SPI_SDCARD_BLOCK_SIZE && ferror(s->image)) {
      clearerr(s->image);
    }
  }
}

static void spisdcard_queue_data_block(struct session_s *s, uint32_t block_index)
{
  uint8_t block_bytes[SPI_SDCARD_BLOCK_SIZE];
  unsigned i;

  spisdcard_load_block(block_index, block_bytes, s);
  spisdcard_queue_byte(s, 0xFEU);
  for (i = 0; i < SPI_SDCARD_BLOCK_SIZE; ++i) {
    spisdcard_queue_byte(s, block_bytes[i]);
  }
  spisdcard_queue_byte(s, 0xFFU);
  spisdcard_queue_byte(s, 0xFFU);
}

static uint32_t spisdcard_block_index_for_arg(const struct session_s *s, uint32_t argument)
{
  if (s->uses_block_addressing) {
    return argument;
  }
  return argument / SPI_SDCARD_BLOCK_SIZE;
}

static void spisdcard_prepare_miso(struct session_s *s)
{
  uint8_t have_byte = 0;

  if (s->miso == NULL) {
    return;
  }
  if (s->cs_n == NULL || *s->cs_n != 0) {
    *s->miso = 1;
    return;
  }
  if (!s->tx_loaded || s->tx_bit_index >= 8U) {
    s->tx_byte = spisdcard_pop_byte(s, &have_byte);
    s->tx_loaded = 1;
    s->tx_bit_index = 0;
    (void)have_byte;
  }
  *s->miso = (uint8_t)((s->tx_byte >> (7U - s->tx_bit_index)) & 0x1U);
}

static void spisdcard_queue_r1(struct session_s *s, uint8_t r1)
{
  spisdcard_queue_byte(s, r1);
}

static void spisdcard_process_command(struct session_s *s)
{
  uint8_t cmd = s->cmd_frame[0] & 0x3FU;
  uint32_t argument =
    ((uint32_t)s->cmd_frame[1] << 24) |
    ((uint32_t)s->cmd_frame[2] << 16) |
    ((uint32_t)s->cmd_frame[3] << 8) |
    (uint32_t)s->cmd_frame[4];

  s->cmd_len = 0;

  switch (cmd) {
  case 0:
    s->acmd_pending = 0;
    s->initialized = 0;
    s->multiblock_active = 0;
    spisdcard_queue_r1(s, 0x01U);
    break;
  case 8:
    spisdcard_queue_r1(s, 0x01U);
    spisdcard_queue_byte(s, 0x00U);
    spisdcard_queue_byte(s, 0x00U);
    spisdcard_queue_byte(s, 0x01U);
    spisdcard_queue_byte(s, 0xAAU);
    break;
  case 12:
    s->multiblock_active = 0;
    s->pending_multiblock_poll = 0;
    spisdcard_queue_byte(s, 0xFFU);
    spisdcard_queue_r1(s, 0x00U);
    break;
  case 16:
    spisdcard_queue_r1(s, 0x00U);
    break;
  case 17:
    spisdcard_queue_r1(s, 0x00U);
    spisdcard_queue_data_block(s, spisdcard_block_index_for_arg(s, argument));
    break;
  case 18:
    s->multiblock_active = 1;
    s->pending_multiblock_poll = 0;
    s->multiblock_next_block = spisdcard_block_index_for_arg(s, argument);
    spisdcard_queue_r1(s, 0x00U);
    spisdcard_queue_data_block(s, s->multiblock_next_block);
    s->multiblock_next_block += 1U;
    break;
  case 55:
    s->acmd_pending = 1;
    spisdcard_queue_r1(s, s->initialized ? 0x00U : 0x01U);
    break;
  case 58:
    s->uses_block_addressing = 1;
    spisdcard_queue_r1(s, 0x00U);
    spisdcard_queue_byte(s, 0x40U);
    spisdcard_queue_byte(s, 0x00U);
    spisdcard_queue_byte(s, 0x00U);
    spisdcard_queue_byte(s, 0x00U);
    break;
  case 41:
    if (s->acmd_pending) {
      s->initialized = 1;
      s->acmd_pending = 0;
      spisdcard_queue_r1(s, 0x00U);
    } else {
      spisdcard_queue_r1(s, 0x04U);
    }
    break;
  default:
    spisdcard_queue_r1(s, 0x04U);
    break;
  }
}

static void spisdcard_handle_received_byte(struct session_s *s, uint8_t byte)
{
  if (s->multiblock_active && spisdcard_queue_count(s) == 0U && s->cmd_len == 0U) {
    if (s->pending_multiblock_poll) {
      s->pending_multiblock_poll = 0;
      if (byte == 0x4CU) {
        s->cmd_frame[0] = byte;
        s->cmd_len = 1U;
        return;
      }
      spisdcard_queue_data_block(s, s->multiblock_next_block);
      s->multiblock_next_block += 1U;
      if (byte == 0xFFU) {
        return;
      }
    } else if (byte == 0xFFU) {
      s->pending_multiblock_poll = 1U;
      return;
    }
  }

  if (s->cmd_len == 0U) {
    if ((byte & 0xC0U) == 0x40U) {
      s->cmd_frame[0] = byte;
      s->cmd_len = 1U;
    }
    return;
  }

  s->cmd_frame[s->cmd_len] = byte;
  s->cmd_len += 1U;
  if (s->cmd_len == 6U) {
    spisdcard_process_command(s);
  }
}

static int spisdcard_start(void *base)
{
  (void)base;
  return RC_OK;
}

static int spisdcard_new(void **sess, char *args)
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

static int spisdcard_add_pads(void *sess, struct pad_list_s *plist)
{
  struct session_s *s = (struct session_s *)sess;

  if (!sess || !plist) {
    return RC_INVARG;
  }

  if (!strcmp(plist->name, "spisdcard")) {
    litex_sim_module_pads_get(plist->pads, "clk", (void **)&s->clk);
    litex_sim_module_pads_get(plist->pads, "mosi", (void **)&s->mosi);
    litex_sim_module_pads_get(plist->pads, "miso", (void **)&s->miso);
    return litex_sim_module_pads_get(plist->pads, "cs_n", (void **)&s->cs_n);
  }

  if (!strcmp(plist->name, "sys_clk")) {
    return litex_sim_module_pads_get(plist->pads, "sys_clk", (void **)&s->sys_clk);
  }

  return RC_OK;
}

static int spisdcard_close(void *sess)
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

static int spisdcard_tick(void *sess, uint64_t time_ps)
{
  struct session_s *s = (struct session_s *)sess;
  clk_edge_t spi_clk_edge;
  int cs_asserted;

  (void)time_ps;
  if (!s || !s->sys_clk || !s->clk || !s->mosi || !s->miso || !s->cs_n) {
    return RC_INVARG;
  }
  if (!clk_pos_edge(&s->sys_edge, *s->sys_clk)) {
    return RC_OK;
  }

  cs_asserted = (*s->cs_n == 0);
  if (!cs_asserted) {
    if (s->selected) {
      spisdcard_reset_selection(s);
      s->pending_multiblock_poll = 0;
      s->multiblock_active = 0;
    }
    *s->miso = 1;
    return RC_OK;
  }

  if (!s->selected) {
    spisdcard_reset_selection(s);
    s->selected = 1;
  }

  if (*s->clk == 0) {
    spisdcard_prepare_miso(s);
  }

  spi_clk_edge = clk_edge(&s->spi_edge, *s->clk);
  if (spi_clk_edge == CLK_EDGE_RISING) {
    s->rx_byte = (uint8_t)((s->rx_byte << 1) | (*s->mosi & 0x1U));
    s->rx_bits += 1U;
    if (s->tx_loaded && s->tx_bit_index < 8U) {
      s->tx_bit_index += 1U;
      if (s->tx_bit_index >= 8U) {
        s->tx_loaded = 0;
      }
    }
    if (s->rx_bits == 8U) {
      spisdcard_handle_received_byte(s, s->rx_byte);
      s->rx_byte = 0;
      s->rx_bits = 0;
    }
  }

  if (*s->clk == 0) {
    spisdcard_prepare_miso(s);
  }

  return RC_OK;
}

static struct ext_module_s ext_mod = {
  "spisdcard",
  spisdcard_start,
  spisdcard_new,
  spisdcard_add_pads,
  spisdcard_close,
  spisdcard_tick
};

int litex_sim_ext_module_init(int (*register_module)(struct ext_module_s *))
{
  return register_module(&ext_mod);
}