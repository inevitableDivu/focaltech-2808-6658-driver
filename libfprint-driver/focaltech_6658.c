/*
 * FocalTech FW9366 / Realtek USB Bridge driver for libfprint
 *
 * Copyright (C) 2026 Divyansh Pandey <pandeydivyansh070501@gmail.com>
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 */

#define FP_COMPONENT "focaltech_6658"

#include "drivers_api.h"
#include "fpi-log.h"
#include "fpi-image-device.h"

#define FT_EP_OUT (0x01 | FPI_USB_ENDPOINT_OUT)
#define FT_EP_IN (0x02 | FPI_USB_ENDPOINT_IN)

#define RAW_WIDTH 64
#define RAW_HEIGHT 80
#define RAW_PIXELS (RAW_WIDTH * RAW_HEIGHT)
#define RAW_BUF_SIZE (RAW_PIXELS * 2)
#define SRAM_FRAME_BASE 0x0200

/*
 * Native sensor pitch is ~50um (508 DPI, ~9px ridge period).
 * A 2x upscale (128x160) keeps ridge period (~18px) inside mindtct's 24x24
 * DFT window, while a 32px border pad prevents mindtct's border margin from
 * clipping edge minutiae on this compact 3.2mm x 4.0mm sensor.
 */
#define SCALE_FACTOR 2
#define SCALED_WIDTH (RAW_WIDTH * SCALE_FACTOR)
#define SCALED_HEIGHT (RAW_HEIGHT * SCALE_FACTOR)
#define BORDER_PAD 32
#define IMAGE_WIDTH (SCALED_WIDTH + (BORDER_PAD * 2))
#define IMAGE_HEIGHT (SCALED_HEIGHT + (BORDER_PAD * 2))
#define SENSOR_PPMM ((508.0 * SCALE_FACTOR) / 25.4)

#define TOUCH_DIFF_THRESHOLD 65
#define TOUCH_MIN_SENSELS 18
#define TOUCH_REQUIRED_STREAK 3
#define RELEASE_REQUIRED_STREAK 2
#define MIN_DYNAMIC_RANGE 120
#define POLL_INTERVAL_MS 50
#define BASELINE_WARMUP_CYCLES 4
#define MAX_STATUS_POLLS 20

/* State machine states */
enum
{
  M_INIT_REG,
  M_INIT_WAKE_DELAY,
  M_INIT_WAKE,
  M_INIT_LOCK_DELAY,
  M_INIT_LOCK,
  M_INIT_CFG_DELAY,
  M_INIT_CFG_1801,
  M_INIT_CFG_1800,
  M_WAIT_POLL,
  M_SCAN_TRIGGER,
  M_SCAN_WAIT,
  M_SCAN_POLL_STATUS_CMD,
  M_SCAN_POLL_STATUS_RX,
  M_READ_CHUNK_CMD,
  M_READ_CHUNK_DATA,
  M_EVALUATE_FRAME,
  M_NUM_STATES,
};

struct _FpiDeviceFocaltech6658
{
  FpImageDevice parent;
  FpiSsm *ssm;
  guint8 *frame_buf;
  gfloat *baseline_buf;
  gboolean hw_initialized;
  gboolean baseline_valid;
  guint warmup_count;
  guint touch_streak;
  guint release_streak;
  guint status_retries;
  gsize read_offset;
  guint poll_count;
  FpiImageDeviceState dev_state;
  gboolean deactivating;
};

G_DECLARE_FINAL_TYPE(FpiDeviceFocaltech6658, fpi_device_focaltech_6658, FPI, DEVICE_FOCALTECH_6658, FpImageDevice);
G_DEFINE_TYPE(FpiDeviceFocaltech6658, fpi_device_focaltech_6658, FP_TYPE_IMAGE_DEVICE);

static const FpIdEntry id_table[] = {
    {
        .vid = 0x2808,
        .pid = 0x6658,
    },
    {
        .vid = 0x2808,
        .pid = 0x9366,
    },
    {
        .vid = 0x2808,
        .pid = 0x6652,
    },
    {
        .vid = 0x2808,
        .pid = 0x9201,
    },
    {.vid = 0, .pid = 0, .driver_data = 0}};

static int
compare_u16(const void *a, const void *b)
{
  guint16 arg1 = *(const guint16 *)a;
  guint16 arg2 = *(const guint16 *)b;
  return (arg1 > arg2) - (arg1 < arg2);
}

static void
ft_send_bulk_cmd(FpiDeviceFocaltech6658 *self, const guint8 *cmd, gsize len)
{
  FpiUsbTransfer *transfer = fpi_usb_transfer_new(FP_DEVICE(self));
  transfer->ssm = self->ssm;
  transfer->short_is_error = TRUE;
  fpi_usb_transfer_fill_bulk_full(transfer, FT_EP_OUT, g_memdup2(cmd, len), len, g_free);
  fpi_usb_transfer_submit(transfer, 1000, fpi_device_get_cancellable(FP_DEVICE(self)),
                          fpi_ssm_usb_transfer_cb, NULL);
}

static void
status_rx_cb(FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658(dev);

  if (error)
  {
    if (!self->deactivating)
      g_warning("[focaltech_6658] Status poll error: %s", error->message);
    fpi_ssm_mark_failed(transfer->ssm, error);
    return;
  }

  if (transfer->actual_length >= 1 && transfer->buffer[0] == 0x54)
  {
    /* Scan complete; proceed to read SRAM frame chunks */
    fpi_ssm_jump_to_state(transfer->ssm, M_READ_CHUNK_CMD);
    return;
  }

  self->status_retries++;
  if (self->status_retries >= MAX_STATUS_POLLS)
  {
    /* Proceed to read even if status register timed out */
    fpi_ssm_jump_to_state(transfer->ssm, M_READ_CHUNK_CMD);
  }
  else
  {
    fpi_ssm_jump_to_state_delayed(transfer->ssm, M_SCAN_POLL_STATUS_CMD, 3);
  }
}

static void
read_chunk_cb(FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658(dev);

  if (error)
  {
    if (!self->deactivating)
      g_warning("[focaltech_6658] Read chunk error: %s", error->message);
    fpi_ssm_mark_failed(transfer->ssm, error);
    return;
  }

  if (transfer->actual_length > 0)
  {
    gsize copy_len = MIN((gsize)transfer->actual_length, RAW_BUF_SIZE - self->read_offset);
    memcpy(self->frame_buf + self->read_offset, transfer->buffer, copy_len);
    self->read_offset += copy_len;
  }

  if (self->read_offset >= RAW_BUF_SIZE)
    fpi_ssm_jump_to_state(transfer->ssm, M_EVALUATE_FRAME);
  else
    fpi_ssm_jump_to_state(transfer->ssm, M_READ_CHUNK_CMD);
}

static FpImage *
focaltech_build_enhanced_image(const guint16 *delta_pixels, guint16 p_low, guint32 range)
{
  guint8 *raw_norm = g_malloc(RAW_PIXELS);
  guint8 *sharpened = g_malloc(RAW_PIXELS);

  /* 1. Contrast-stretch baseline-subtracted delta to 0..255 (255 = strong ridge signal) */
  for (int i = 0; i < RAW_PIXELS; i++)
  {
    guint16 px = delta_pixels[i];
    if (px < p_low)
      px = p_low;
    guint32 val = ((guint32)(px - p_low) * 255U) / range;
    raw_norm[i] = (guint8)CLAMP(val, 0U, 255U);
  }

  /* 2. Apply 3x3 unsharp mask on native 64x80 grid to accentuate ridge-valley transitions */
  for (int y = 0; y < RAW_HEIGHT; y++)
  {
  for (int x = 0; x < RAW_WIDTH; x++)
  {
  int sum = 0;
  int count = 0;
  for (int dy = -1; dy <= 1; dy++)
  {
  int ny = CLAMP (y + dy, 0, RAW_HEIGHT - 1);
  for (int dx = -1; dx <= 1; dx++)
  {
  int nx = CLAMP (x + dx, 0, RAW_WIDTH - 1);
  sum += raw_norm[ny * RAW_WIDTH + nx];
  count++;
  }
  }
  int mean = sum / count;
  int center = raw_norm[y * RAW_WIDTH + x];
  /* Boost local ridge contrast around local mean */
  int enhanced = center + ((center - mean) * 3) / 2;
  sharpened[y * RAW_WIDTH + x] = (guint8)CLAMP(enhanced, 0, 255);
}
}

/*

Create output image (192x224) with neutral background (0 before inversion -> 255 white after)

and smooth 2x interpolated active sensor region (128x160) centered inside.
*/
FpImage *img = fp_image_new(IMAGE_WIDTH, IMAGE_HEIGHT);
img->ppmm = SENSOR_PPMM;
img->flags = FPI_IMAGE_COLORS_INVERTED;
memset(img->data, 0, IMAGE_WIDTH *IMAGE_HEIGHT);

for (int y = 0; y < SCALED_HEIGHT; y++)
{
  float gy = (float)y / (float)SCALE_FACTOR;
  int y0 = (int)gy;
  int y1 = (y0 + 1 < RAW_HEIGHT) ? (y0 + 1) : y0;
  float dy = gy - y0;

  for (int x = 0; x < SCALED_WIDTH; x++)
  {
    float gx = (float)x / (float)SCALE_FACTOR;
    int x0 = (int)gx;
    int x1 = (x0 + 1 < RAW_WIDTH) ? (x0 + 1) : x0;
    float dx = gx - x0;

    float v00 = sharpened[y0 * RAW_WIDTH + x0];
    float v01 = sharpened[y0 * RAW_WIDTH + x1];
    float v10 = sharpened[y1 * RAW_WIDTH + x0];
    float v11 = sharpened[y1 * RAW_WIDTH + x1];

    float v = (1.0f - dx) * (1.0f - dy) * v00 +
              dx * (1.0f - dy) * v01 +
              (1.0f - dx) * dy * v10 +
              dx * dy * v11;

    /* Taper 4px edge border smoothly into the neutral pad to avoid hard box edges */
    float edge_weight = 1.0f;
    if (x < 4)
      edge_weight *= (float)x / 4.0f;
    if (y < 4)
      edge_weight *= (float)y / 4.0f;
    if (x >= SCALED_WIDTH - 4)
      edge_weight *= (float)(SCALED_WIDTH - 1 - x) / 4.0f;
    if (y >= SCALED_HEIGHT - 4)
      edge_weight *= (float)(SCALED_HEIGHT - 1 - y) / 4.0f;

    img->data[(y + BORDER_PAD) * IMAGE_WIDTH + (x + BORDER_PAD)] = (guint8)(v * edge_weight);
  }
}

g_free(raw_norm);
g_free(sharpened);
return img;
}

static void
focaltech_loop_state(FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658(dev);

  if (self->deactivating)
  {
    fpi_ssm_mark_completed(ssm);
    return;
  }

  switch (fpi_ssm_get_cur_state(ssm))
  {
  case M_INIT_REG:
    if (self->hw_initialized)
    {
      fpi_ssm_jump_to_state(ssm, M_WAIT_POLL);
      return;
    }
    {
      static const guint8 pkt[] = {0x09, 0xF6, 0xC6, 0x00};
      ft_send_bulk_cmd(self, pkt, sizeof(pkt));
    }
    break;

  case M_INIT_WAKE_DELAY:
    fpi_ssm_next_state_delayed(ssm, 10);
    break;

  case M_INIT_WAKE:
  {
    static const guint8 pkt[] = {0x5A, 0xA5, 0x00};
    ft_send_bulk_cmd(self, pkt, sizeof(pkt));
  }
  break;

  case M_INIT_LOCK_DELAY:
    fpi_ssm_next_state_delayed(ssm, 10);
    break;

  case M_INIT_LOCK:
  {
    static const guint8 pkt[] = {0xA5, 0x5A, 0x00};
    ft_send_bulk_cmd(self, pkt, sizeof(pkt));
  }
  break;

  case M_INIT_CFG_DELAY:
    fpi_ssm_next_state_delayed(ssm, 10);
    break;

  case M_INIT_CFG_1801:
  {
    static const guint8 pkt[] = {0x05, 0xFA, 0x98, 0x01, 0x00, 0x01, 0xA7, 0xFC};
    ft_send_bulk_cmd(self, pkt, sizeof(pkt));
  }
  break;

  case M_INIT_CFG_1800:
  {
    static const guint8 pkt[] = {0x05, 0xFA, 0x98, 0x00, 0x00, 0x01, 0xFE, 0x4F};
    self->hw_initialized = TRUE;
    g_message("[focaltech_6658] AFE initialized; continuous matrix scanning active");
    ft_send_bulk_cmd(self, pkt, sizeof(pkt));
  }
  break;

  case M_WAIT_POLL:
    fpi_ssm_next_state_delayed(ssm, POLL_INTERVAL_MS);
    break;

  case M_SCAN_TRIGGER:
    self->read_offset = 0;
    self->status_retries = 0;
    {
      static const guint8 pkt[] = {0xC4, 0x3B, 0x00};
      ft_send_bulk_cmd(self, pkt, sizeof(pkt));
    }
    break;

  case M_SCAN_WAIT:
    fpi_ssm_next_state_delayed(ssm, 30);
    break;

  case M_SCAN_POLL_STATUS_CMD:
  {
    static const guint8 pkt[] = {0x08, 0xF7, 0x80, 0x00, 0x00};
    ft_send_bulk_cmd(self, pkt, sizeof(pkt));
  }
  break;

  case M_SCAN_POLL_STATUS_RX:
  {
    FpiUsbTransfer *rx = fpi_usb_transfer_new(FP_DEVICE(self));
    rx->ssm = ssm;
    fpi_usb_transfer_fill_bulk(rx, FT_EP_IN, 1);
    fpi_usb_transfer_submit(rx, 500, fpi_device_get_cancellable(FP_DEVICE(self)),
                            status_rx_cb, NULL);
  }
  break;

  case M_READ_CHUNK_CMD:
  {
    guint16 cur_addr = SRAM_FRAME_BASE + self->read_offset;
    guint8 sram_cmd[6] = {
        0x04, 0xFB,
        (guint8)(((cur_addr >> 8) | 0x80) & 0xFF),
        (guint8)(cur_addr & 0xFF),
        0x01, 0x00 /* 256 words = 512 bytes */
    };
    ft_send_bulk_cmd(self, sram_cmd, sizeof(sram_cmd));
  }
  break;

  case M_READ_CHUNK_DATA:
  {
    FpiUsbTransfer *rx = fpi_usb_transfer_new(FP_DEVICE(self));
    rx->ssm = ssm;
    fpi_usb_transfer_fill_bulk(rx, FT_EP_IN, 512);
    fpi_usb_transfer_submit(rx, 500, fpi_device_get_cancellable(FP_DEVICE(self)),
                            read_chunk_cb, NULL);
  }
  break;

  case M_EVALUATE_FRAME:
  {
    guint16 *cur_pixels = g_malloc(RAW_PIXELS * sizeof(guint16));
    for (int i = 0; i < RAW_PIXELS; i++)
      cur_pixels[i] = ((guint16)self->frame_buf[i * 2] << 8) | self->frame_buf[i * 2 + 1];

    /* Initial baseline acquisition (only once per session before touch) */
    if (!self->baseline_valid)
    {
      for (int i = 0; i < RAW_PIXELS; i++)
      {
        if (self->warmup_count == 0)
          self->baseline_buf[i] = (gfloat)cur_pixels[i];
        else
          self->baseline_buf[i] = self->baseline_buf[i] * 0.7f + (gfloat)cur_pixels[i] * 0.3f;
      }
      self->warmup_count++;
      if (self->warmup_count >= BASELINE_WARMUP_CYCLES)
      {
        self->baseline_valid = TRUE;
        g_message("[focaltech_6658] Baseline FPN calibration complete (%u frames)",
                  self->warmup_count);
      }
      g_free(cur_pixels);
      fpi_ssm_jump_to_state(ssm, M_WAIT_POLL);
      return;
    }

    /* Compute per-sensel baseline-subtracted delta (eliminates static FPN) */
    guint16 *delta_pixels = g_malloc0(RAW_PIXELS * sizeof(guint16));
    gfloat max_diff = 0;
    guint touch_count = 0;
    gfloat sum_diff = 0;
    guint valid_count = 0;

    for (int i = 0; i < RAW_PIXELS; i++)
    {
      gfloat b = self->baseline_buf[i];
      gfloat c = (gfloat)cur_pixels[i];
      if (b < 60000.0f && c < 60000.0f)
      {
        gfloat diff = (c > b) ? (c - b) : (b - c);
        delta_pixels[i] = (guint16)CLAMP(diff, 0.0f, 65535.0f);
        if (diff > max_diff)
          max_diff = diff;
        if (diff > 50.0f)
          touch_count++;
        sum_diff += diff;
        valid_count++;
      }
    }

    gfloat mean_energy = (valid_count > 0) ? (sum_diff / (gfloat)valid_count) : 0;
    gboolean is_touching = (max_diff > (gfloat)TOUCH_DIFF_THRESHOLD &&
                            touch_count >= TOUCH_MIN_SENSELS) ||
                           (mean_energy > 4.5f && touch_count >= TOUCH_MIN_SENSELS);

    self->poll_count++;

    /*
     * Mode 1: Waiting for finger removal (FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_OFF)
     * Do NOT capture and do NOT corrupt baseline while user lifts finger.
     */
    if (self->dev_state == FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_OFF)
    {
      if (!is_touching)
      {
        self->release_streak++;
        if (self->release_streak >= RELEASE_REQUIRED_STREAK)
        {
          g_message("[focaltech_6658] Finger lifted off sensor");
          self->release_streak = 0;
          self->touch_streak = 0;
          fpi_image_device_report_finger_status(FP_IMAGE_DEVICE(self), FALSE);
        }
      }
      else
      {
        self->release_streak = 0;
      }

      g_free(delta_pixels);
      g_free(cur_pixels);
      fpi_ssm_jump_to_state(ssm, M_WAIT_POLL);
      return;
    }

    /*
     * Mode 2: Waiting for finger press (AWAIT_FINGER_ON or CAPTURE)
     */
    if (is_touching)
      self->touch_streak++;
    else
      self->touch_streak = 0;

    if (self->poll_count % 10 == 0 || self->touch_streak > 0)
    {
      g_message("[focaltech_6658] Poll #%u: active_sensels=%u, max_diff=%.1f, mean=%.2f, streak=%u",
                self->poll_count, touch_count, max_diff, mean_energy, self->touch_streak);
    }

    if (self->touch_streak >= TOUCH_REQUIRED_STREAK)
    {
      /* Evaluate dynamic range on the FPN-subtracted delta_pixels, NOT raw cur_pixels! */
      guint16 *sorted = g_memdup2(delta_pixels, RAW_PIXELS * sizeof(guint16));
      qsort(sorted, RAW_PIXELS, sizeof(guint16), compare_u16);
      guint16 p_low = sorted[(RAW_PIXELS * 5) / 100];
      guint16 p_high = sorted[(RAW_PIXELS * 98) / 100];
      g_free(sorted);

      guint32 range = (p_high > p_low) ? (p_high - p_low) : 1;

      if (range < MIN_DYNAMIC_RANGE)
      {
        g_message("[focaltech_6658] Frame rejected (delta dynamic range=%u < %u). Waiting for firmer press...",
                  range, MIN_DYNAMIC_RANGE);
        g_free(delta_pixels);
        g_free(cur_pixels);
        fpi_ssm_jump_to_state(ssm, M_WAIT_POLL);
        return;
      }

      g_message("[focaltech_6658] *** VERIFIED FINGERPRINT CAPTURED (streak=%u, sensels=%u, delta_range=%u) ***",
                self->touch_streak, touch_count, range);

      self->touch_streak = 0;
      self->release_streak = 0;

      fpi_image_device_report_finger_status(FP_IMAGE_DEVICE(self), TRUE);

      FpImage *img = focaltech_build_enhanced_image(delta_pixels, p_low, range);

      g_free(delta_pixels);
      g_free(cur_pixels);

      g_message("[focaltech_6658] Frame delivered to mindtct: delta_p5=%u, delta_p98=%u, dim=%dx%d, ppmm=%.2f",
                p_low, p_high, IMAGE_WIDTH, IMAGE_HEIGHT, img->ppmm);

      /*
       * Submitting the image transitions libfprint to FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_OFF.
       * Keep the SSM polling so we detect physical finger lift before reporting finger FALSE.
       */
      self->dev_state = FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_OFF;
      fpi_image_device_image_captured(FP_IMAGE_DEVICE(self), img);
      fpi_ssm_jump_to_state(ssm, M_WAIT_POLL);
      return;
    }

    /* Slowly track thermal drift in baseline ONLY when sensor is completely untouched */
    if (!is_touching && max_diff < 35.0f && touch_count < 3)
    {
      for (int i = 0; i < RAW_PIXELS; i++)
        self->baseline_buf[i] = self->baseline_buf[i] * 0.92f + (gfloat)cur_pixels[i] * 0.08f;
    }

    g_free(delta_pixels);
    g_free(cur_pixels);
    fpi_ssm_jump_to_state(ssm, M_WAIT_POLL);
  }
  break;
  }
}

static void
focaltech_loop_complete(FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658(dev);

  self->ssm = NULL;
  if (self->deactivating)
    fpi_image_device_deactivate_complete(FP_IMAGE_DEVICE(self), error);
  else if (error != NULL)
    fpi_image_device_session_error(FP_IMAGE_DEVICE(self), error);
}

/* Open sequence */
static void
focaltech_dev_open(FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658(dev);
  GError *error = NULL;

  g_usb_device_claim_interface(fpi_device_get_usb_device(FP_DEVICE(dev)), 0, 0, &error);
  if (error)
  {
    g_warning("[focaltech_6658] Open error: %s", error->message);
    fpi_image_device_open_complete(dev, error);
    return;
  }

  self->frame_buf = g_malloc0(RAW_BUF_SIZE);
  self->baseline_buf = g_malloc0(RAW_PIXELS * sizeof(gfloat));
  self->hw_initialized = FALSE;
  self->baseline_valid = FALSE;
  self->warmup_count = 0;
  self->touch_streak = 0;
  self->release_streak = 0;
  self->poll_count = 0;
  fpi_image_device_open_complete(dev, NULL);
  g_message("[focaltech_6658] Device opened successfully (2808:6658)");
}

/* Close sequence */
static void
focaltech_dev_close(FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658(dev);
  GError *error = NULL;

  g_clear_pointer(&self->frame_buf, g_free);
  g_clear_pointer(&self->baseline_buf, g_free);
  g_usb_device_release_interface(fpi_device_get_usb_device(FP_DEVICE(dev)), 0, 0, &error);
  fpi_image_device_close_complete(dev, error);
  g_message("[focaltech_6658] Device closed");
}

/* Activate */
static void
focaltech_dev_activate(FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658(dev);
  self->deactivating = FALSE;
  self->hw_initialized = FALSE;
  self->baseline_valid = FALSE;
  self->warmup_count = 0;
  self->touch_streak = 0;
  self->release_streak = 0;
  self->poll_count = 0;
  self->dev_state = FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_ON;
  g_message("[focaltech_6658] Device activated");
  fpi_image_device_activate_complete(dev, NULL);
}

/* Deactivate */
static void
focaltech_dev_deactivate(FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658(dev);

  self->deactivating = TRUE;
  self->hw_initialized = FALSE;
  g_message("[focaltech_6658] Device deactivating");
  if (self->ssm == NULL)
    fpi_image_device_deactivate_complete(dev, NULL);
}

/* Change state */
static void
focaltech_dev_change_state(FpImageDevice *dev, FpiImageDeviceState state)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658(dev);

  if (self->deactivating)
    return;

  g_message("[focaltech_6658] State change notification: %d", state);
  self->dev_state = state;

  if (state == FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_ON)
  {
    /*
     * CRITICAL: Do NOT reset warmup_count or baseline_valid here!
     * Only reset streak counters so multi-stage enrollment preserves the
     * clean empty-sensor baseline calibrated at session start.
     */
    self->touch_streak = 0;
    self->release_streak = 0;
    if (!self->ssm)
    {
      self->ssm = fpi_ssm_new(FP_DEVICE(self), focaltech_loop_state, M_NUM_STATES);
      fpi_ssm_start(self->ssm, focaltech_loop_complete);
    }
  }
}

static void
fpi_device_focaltech_6658_init(FpiDeviceFocaltech6658 *self)
{
}

static void
fpi_device_focaltech_6658_class_init(FpiDeviceFocaltech6658Class *klass)
{
  FpDeviceClass *dev_class = FP_DEVICE_CLASS(klass);
  FpImageDeviceClass *img_class = FP_IMAGE_DEVICE_CLASS(klass);

  dev_class->id = "focaltech_6658";
  dev_class->full_name = "FocalTech FW9366 Fingerprint Sensor";
  dev_class->type = FP_DEVICE_TYPE_USB;
  dev_class->id_table = id_table;
  dev_class->scan_type = FP_SCAN_TYPE_PRESS;
  dev_class->temp_hot_seconds = 0;

  img_class->img_open = focaltech_dev_open;
  img_class->img_close = focaltech_dev_close;
  img_class->activate = focaltech_dev_activate;
  img_class->deactivate = focaltech_dev_deactivate;
  img_class->change_state = focaltech_dev_change_state;

  img_class->img_width = IMAGE_WIDTH;
  img_class->img_height = IMAGE_HEIGHT;
  img_class->bz3_threshold = 9;
}