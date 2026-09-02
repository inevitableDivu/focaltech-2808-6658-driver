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
#define FT_EP_IN  (0x02 | FPI_USB_ENDPOINT_IN)

#define RAW_WIDTH       64
#define RAW_HEIGHT      80
#define RAW_PIXELS      (RAW_WIDTH * RAW_HEIGHT)
#define RAW_BUF_SIZE    (RAW_PIXELS * 2)
#define SRAM_FRAME_BASE 0x0200

#define SCALE_FACTOR    2
#define IMAGE_WIDTH     (RAW_WIDTH * SCALE_FACTOR)
#define IMAGE_HEIGHT    (RAW_HEIGHT * SCALE_FACTOR)
#define SENSOR_PPMM     (500.0 / 25.4) /* Standard 500 DPI for NIST NBIS */

#define TOUCH_DIFF_THRESHOLD 25
#define POLL_INTERVAL_MS     60

/* State machine states */
enum {
  M_INIT_REG,
  M_INIT_WAKE,
  M_INIT_LOCK,
  M_INIT_CFG_1801,
  M_INIT_CFG_1800,
  M_WAIT_POLL,
  M_SCAN_TRIGGER,
  M_SCAN_WAIT,
  M_READ_CHUNK,
  M_EVALUATE_FRAME,
  M_NUM_STATES,
};

struct _FpiDeviceFocaltech6658
{
  FpImageDevice parent;
  FpiSsm       *ssm;
  guint8       *frame_buf;
  guint16      *baseline_buf;
  gboolean      has_baseline;
  gsize         read_offset;
  guint         poll_count;
  gboolean      deactivating;
};

G_DECLARE_FINAL_TYPE (FpiDeviceFocaltech6658, fpi_device_focaltech_6658, FPI, DEVICE_FOCALTECH_6658, FpImageDevice);
G_DEFINE_TYPE (FpiDeviceFocaltech6658, fpi_device_focaltech_6658, FP_TYPE_IMAGE_DEVICE);

static const FpIdEntry id_table[] = {
  { .vid = 0x2808, .pid = 0x6658, },
  { .vid = 0x2808, .pid = 0x9366, },
  { .vid = 0x2808, .pid = 0x6652, },
  { .vid = 0x2808, .pid = 0x9201, },
  { .vid = 0, .pid = 0, .driver_data = 0 }
};

static void
ft_send_bulk_cmd (FpiDeviceFocaltech6658 *self, const guint8 *cmd, gsize len)
{
  FpiUsbTransfer *transfer = fpi_usb_transfer_new (FP_DEVICE (self));
  transfer->ssm = self->ssm;
  transfer->short_is_error = TRUE;
  fpi_usb_transfer_fill_bulk_full (transfer, FT_EP_OUT, g_memdup2 (cmd, len), len, g_free);
  fpi_usb_transfer_submit (transfer, 1000, fpi_device_get_cancellable (FP_DEVICE (self)),
                           fpi_ssm_usb_transfer_cb, NULL);
}

static void
dummy_tx_cb (FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  /* OUT command sent; IN transfer handles state completion */
}

static void
read_chunk_cb (FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (error)
    {
      if (!self->deactivating)
        g_warning ("[focaltech_6658] Read chunk error: %s", error->message);
      fpi_ssm_mark_failed (transfer->ssm, error);
      return;
    }

  if (transfer->actual_length > 0)
    {
      memcpy (self->frame_buf + self->read_offset, transfer->buffer, transfer->actual_length);
      self->read_offset += transfer->actual_length;
    }

  if (self->read_offset >= RAW_BUF_SIZE)
    fpi_ssm_jump_to_state (transfer->ssm, M_EVALUATE_FRAME);
  else
    fpi_ssm_jump_to_state (transfer->ssm, M_READ_CHUNK);
}

static void
focaltech_loop_state (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (self->deactivating)
    {
      fpi_ssm_mark_completed (ssm);
      return;
    }

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case M_INIT_REG:
      {
        static const guint8 pkt[] = { 0x09, 0xF6, 0xC6, 0x00 };
        ft_send_bulk_cmd (self, pkt, sizeof (pkt));
      }
      break;

    case M_INIT_WAKE:
      {
        static const guint8 pkt[] = { 0x5A, 0xA5, 0x00 };
        ft_send_bulk_cmd (self, pkt, sizeof (pkt));
      }
      break;

    case M_INIT_LOCK:
      {
        static const guint8 pkt[] = { 0xA5, 0x5A, 0x00 };
        ft_send_bulk_cmd (self, pkt, sizeof (pkt));
      }
      break;

    case M_INIT_CFG_1801:
      {
        static const guint8 pkt[] = { 0x05, 0xFA, 0x98, 0x01, 0x00, 0x01, 0xA7, 0xFC };
        ft_send_bulk_cmd (self, pkt, sizeof (pkt));
      }
      break;

    case M_INIT_CFG_1800:
      {
        static const guint8 pkt[] = { 0x05, 0xFA, 0x98, 0x00, 0x00, 0x01, 0xFE, 0x4F };
        g_message ("[focaltech_6658] Continuous matrix scanning active");
        ft_send_bulk_cmd (self, pkt, sizeof (pkt));
      }
      break;

    case M_WAIT_POLL:
      fpi_ssm_next_state_delayed (ssm, POLL_INTERVAL_MS);
      break;

    case M_SCAN_TRIGGER:
      self->read_offset = 0;
      {
        static const guint8 pkt[] = { 0xC4, 0x3B, 0x00 };
        ft_send_bulk_cmd (self, pkt, sizeof (pkt));
      }
      break;

    case M_SCAN_WAIT:
      fpi_ssm_next_state_delayed (ssm, 35);
      break;

    case M_READ_CHUNK:
      {
        guint16 cur_addr = SRAM_FRAME_BASE + self->read_offset;
        guint8 sram_cmd[6] = {
          0x04, 0xFB,
          (guint8)(((cur_addr >> 8) | 0x80) & 0xFF),
          (guint8)(cur_addr & 0xFF),
          0x01, 0x00 /* 256 words = 512 bytes */
        };

        FpiUsbTransfer *tx = fpi_usb_transfer_new (FP_DEVICE (self));
        tx->short_is_error = TRUE;
        fpi_usb_transfer_fill_bulk_full (tx, FT_EP_OUT, g_memdup2 (sram_cmd, 6), 6, g_free);
        fpi_usb_transfer_submit (tx, 500, fpi_device_get_cancellable (FP_DEVICE (self)),
                                 dummy_tx_cb, NULL);

        FpiUsbTransfer *rx = fpi_usb_transfer_new (FP_DEVICE (self));
        rx->ssm = ssm;
        fpi_usb_transfer_fill_bulk (rx, FT_EP_IN, 512);
        fpi_usb_transfer_submit (rx, 500, fpi_device_get_cancellable (FP_DEVICE (self)),
                                 read_chunk_cb, NULL);
      }
      break;

    case M_EVALUATE_FRAME:
      {
        guint16 *cur_pixels = g_malloc (RAW_PIXELS * sizeof (guint16));
        for (int i = 0; i < RAW_PIXELS; i++)
          cur_pixels[i] = (self->frame_buf[i * 2] << 8) | self->frame_buf[i * 2 + 1];

        if (!self->has_baseline)
          {
            memcpy (self->baseline_buf, cur_pixels, RAW_PIXELS * sizeof (guint16));
            self->has_baseline = TRUE;
            g_free (cur_pixels);
            g_message ("[focaltech_6658] Idle sensor matrix baseline calibrated");
            fpi_ssm_jump_to_state (ssm, M_WAIT_POLL);
            return;
          }

        /* Calculate delta image and find max touch deflection */
        guint16 *delta = g_malloc0 (RAW_PIXELS * sizeof (guint16));
        guint16 max_diff = 0;
        guint touch_count = 0;

        for (int i = 0; i < RAW_PIXELS; i++)
          {
            guint16 b = self->baseline_buf[i];
            guint16 c = cur_pixels[i];
            if (b < 60000 && c < 60000)
              {
                guint16 diff = (c > b) ? (c - b) : (b - c);
                delta[i] = diff;
                if (diff > max_diff) max_diff = diff;
                if (diff > 15) touch_count++;
              }
          }

        self->poll_count++;
        if (self->poll_count % 10 == 0 || touch_count > 0)
          {
            g_message ("[focaltech_6658] Matrix poll #%u: active_sensels=%u, max_diff=%u",
                       self->poll_count, touch_count, max_diff);
          }

        if (max_diff > TOUCH_DIFF_THRESHOLD || touch_count >= 8)
          {
            g_message ("[focaltech_6658] *** FINGER TOUCH DETECTED! (sensels=%u, max_diff=%u) ***",
                       touch_count, max_diff);

            fpi_image_device_report_finger_status (FP_IMAGE_DEVICE (self), TRUE);

            /* Create NIST-optimized image */
            FpImage *img = fp_image_new (IMAGE_WIDTH, IMAGE_HEIGHT);
            img->ppmm = SENSOR_PPMM;
            img->flags = FPI_IMAGE_COLORS_INVERTED;

            guint8 *raw_norm = g_malloc (RAW_PIXELS);
            guint32 range = (max_diff > 0) ? max_diff : 1;

            for (int i = 0; i < RAW_PIXELS; i++)
              {
                guint32 val = ((guint32) delta[i] * 255) / range;
                if (val > 255) val = 255;
                raw_norm[i] = (guint8) val;
              }

            /* Bilinear upsample 2x to 128x160 with smooth interpolation */
            for (int y = 0; y < IMAGE_HEIGHT; y++)
              {
                int src_y = y / SCALE_FACTOR;
                for (int x = 0; x < IMAGE_WIDTH; x++)
                  {
                    int src_x = x / SCALE_FACTOR;
                    img->data[y * IMAGE_WIDTH + x] = raw_norm[src_y * RAW_WIDTH + src_x];
                  }
              }

            g_free (raw_norm);
            g_free (delta);
            g_free (cur_pixels);

            g_message ("[focaltech_6658] Clean subtracted frame delivered to mindtct: max_delta=%d, dim=%dx%d, ppmm=%.2f",
                       max_diff, IMAGE_WIDTH, IMAGE_HEIGHT, img->ppmm);

            fpi_image_device_image_captured (FP_IMAGE_DEVICE (self), img);
            fpi_ssm_mark_completed (ssm);
            fpi_image_device_report_finger_status (FP_IMAGE_DEVICE (self), FALSE);
            return;
          }

        g_free (delta);
        g_free (cur_pixels);
        fpi_ssm_jump_to_state (ssm, M_WAIT_POLL);
      }
      break;
    }
}

static void
focaltech_loop_complete (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  self->ssm = NULL;
  if (self->deactivating)
    fpi_image_device_deactivate_complete (FP_IMAGE_DEVICE (self), error);
  else if (error != NULL)
    fpi_image_device_session_error (FP_IMAGE_DEVICE (self), error);
}

/* Open sequence */
static void
focaltech_dev_open (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  GError *error = NULL;

  g_usb_device_claim_interface (fpi_device_get_usb_device (FP_DEVICE (dev)), 0, 0, &error);
  if (error)
    {
      g_warning ("[focaltech_6658] Open error: %s", error->message);
      fpi_image_device_open_complete (dev, error);
      return;
    }

  self->frame_buf = g_malloc0 (RAW_BUF_SIZE);
  self->baseline_buf = g_malloc0 (RAW_PIXELS * sizeof (guint16));
  self->has_baseline = FALSE;
  self->poll_count = 0;
  fpi_image_device_open_complete (dev, NULL);
  g_message ("[focaltech_6658] Device opened successfully (2808:6658)");
}

/* Close sequence */
static void
focaltech_dev_close (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  GError *error = NULL;

  g_clear_pointer (&self->frame_buf, g_free);
  g_clear_pointer (&self->baseline_buf, g_free);
  g_usb_device_release_interface (fpi_device_get_usb_device (FP_DEVICE (dev)), 0, 0, &error);
  fpi_image_device_close_complete (dev, error);
  g_message ("[focaltech_6658] Device closed");
}

/* Activate */
static void
focaltech_dev_activate (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  self->deactivating = FALSE;
  self->has_baseline = FALSE;
  g_message ("[focaltech_6658] Device activated");
  fpi_image_device_activate_complete (dev, NULL);
}

/* Deactivate */
static void
focaltech_dev_deactivate (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  self->deactivating = TRUE;
  g_message ("[focaltech_6658] Device deactivating");
  if (self->ssm)
    {
      fpi_ssm_cancel_delayed_state_change (self->ssm);
      fpi_ssm_mark_completed (self->ssm);
    }
  else
    {
      fpi_image_device_deactivate_complete (dev, NULL);
    }
}

/* Change state */
static void
focaltech_dev_change_state (FpImageDevice *dev, FpiImageDeviceState state)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (self->deactivating)
    return;

  g_message ("[focaltech_6658] State change notification: %d", state);

  if (state == FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_ON)
    {
      if (!self->ssm)
        {
          self->poll_count = 0;
          self->ssm = fpi_ssm_new (FP_DEVICE (self), focaltech_loop_state, M_NUM_STATES);
          fpi_ssm_start (self->ssm, focaltech_loop_complete);
        }
    }
}

static void
fpi_device_focaltech_6658_init (FpiDeviceFocaltech6658 *self)
{
}

static void
fpi_device_focaltech_6658_class_init (FpiDeviceFocaltech6658Class *klass)
{
  FpDeviceClass *dev_class = FP_DEVICE_CLASS (klass);
  FpImageDeviceClass *img_class = FP_IMAGE_DEVICE_CLASS (klass);

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
  img_class->bz3_threshold = 24;
}
