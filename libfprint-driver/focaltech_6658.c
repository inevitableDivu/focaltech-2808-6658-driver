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

#define RAW_WIDTH      64
#define RAW_HEIGHT     80
#define RAW_PIXELS     (RAW_WIDTH * RAW_HEIGHT)
#define RAW_BUF_SIZE   (RAW_PIXELS * 2)
#define SRAM_FRAME_BASE 0x0200

#define SCALE_FACTOR   2
#define IMAGE_WIDTH    (RAW_WIDTH * SCALE_FACTOR)
#define IMAGE_HEIGHT   (RAW_HEIGHT * SCALE_FACTOR)
#define SENSOR_PPMM    ((508.0 * SCALE_FACTOR) / 25.4)

#define FDT_TOUCH_THRESHOLD   50
#define FDT_RELEASE_THRESHOLD 25
#define FDT_INTEGRATION_MS    10
#define FDT_POLL_DELAY_MS     50

/* USB command packets */
static const guint8 cmd_fdt_sense[] = { 0xC2, 0x3D, 0x00 };
static const guint8 cmd_scan_img[]  = { 0xC4, 0x3B, 0x00 };

/* FDT Sense SSM states */
enum {
  FDT_STATE_INIT_AFE,
  FDT_STATE_ENABLE,
  FDT_STATE_WAIT_POLL,
  FDT_STATE_SENSE,
  FDT_STATE_WAIT_INTEGRATE,
  FDT_STATE_READ_CMD,
  FDT_STATE_READ_DATA,
  FDT_NUM_STATES,
};

/* Capture SSM states */
enum {
  CAP_STATE_PREPARE,
  CAP_STATE_START,
  CAP_STATE_WAIT,
  CAP_STATE_READ_CHUNK,
  CAP_STATE_PROCESS,
  CAP_NUM_STATES,
};

/* Finger-Off SSM states */
enum {
  OFF_STATE_WAIT_POLL,
  OFF_STATE_SENSE,
  OFF_STATE_WAIT_INTEGRATE,
  OFF_STATE_READ_CMD,
  OFF_STATE_READ_DATA,
  OFF_NUM_STATES,
};

struct _FpiDeviceFocaltech6658
{
  FpImageDevice parent;
  FpiSsm       *active_ssm;
  guint8       *frame_buf;
  gsize         read_offset;
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

static int
compare_u16 (const void *a, const void *b)
{
  guint16 arg1 = *(const guint16 *) a;
  guint16 arg2 = *(const guint16 *) b;
  return (arg1 > arg2) - (arg1 < arg2);
}

static void
ft_send_bulk_cmd (FpiDeviceFocaltech6658 *self, const guint8 *cmd, gsize len)
{
  FpiUsbTransfer *transfer = fpi_usb_transfer_new (FP_DEVICE (self));
  transfer->ssm = self->active_ssm;
  transfer->short_is_error = TRUE;
  fpi_usb_transfer_fill_bulk_full (transfer, FT_EP_OUT, g_memdup2 (cmd, len), len, g_free);
  fpi_usb_transfer_submit (transfer, 1000, fpi_device_get_cancellable (FP_DEVICE (self)),
                           fpi_ssm_usb_transfer_cb, NULL);
}

/* ========================================================================= */
/* Phase 1: Finger Detect (FDT) SSM                                          */
/* ========================================================================= */

static void
fdt_read_cb (FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (error)
    {
      fpi_ssm_mark_failed (transfer->ssm, error);
      return;
    }

  if (transfer->actual_length >= 8)
    {
      guint16 d0 = (transfer->buffer[0] << 8) | transfer->buffer[1];
      guint16 d1 = (transfer->buffer[2] << 8) | transfer->buffer[3];
      guint16 d2 = (transfer->buffer[4] << 8) | transfer->buffer[5];
      guint16 d3 = (transfer->buffer[6] << 8) | transfer->buffer[7];

      if (d0 > FDT_TOUCH_THRESHOLD || d1 > FDT_TOUCH_THRESHOLD ||
          d2 > FDT_TOUCH_THRESHOLD || d3 > FDT_TOUCH_THRESHOLD)
        {
          fp_dbg ("Finger touch detected: [%d, %d, %d, %d]", d0, d1, d2, d3);
          fpi_ssm_mark_completed (transfer->ssm);
          fpi_image_device_report_finger_status (FP_IMAGE_DEVICE (self), TRUE);
          return;
        }
    }

  fpi_ssm_jump_to_state (transfer->ssm, FDT_STATE_WAIT_POLL);
}

static void
fdt_ssm_state (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (self->deactivating)
    {
      fpi_ssm_mark_completed (ssm);
      return;
    }

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case FDT_STATE_INIT_AFE:
      {
        static const guint8 init_pkt[] = {
          0x09, 0xF6, 0xC6, 0x00,
          0x5A, 0xA5, 0x00,
          0xA5, 0x5A, 0x00
        };
        ft_send_bulk_cmd (self, init_pkt, sizeof (init_pkt));
      }
      break;

    case FDT_STATE_ENABLE:
      {
        static const guint8 fdt_on_pkt[] = { 0x09, 0xF6, 0x9A, 0x5A };
        ft_send_bulk_cmd (self, fdt_on_pkt, sizeof (fdt_on_pkt));
      }
      break;

    case FDT_STATE_WAIT_POLL:
      fpi_ssm_next_state_delayed (ssm, FDT_POLL_DELAY_MS);
      break;

    case FDT_STATE_SENSE:
      ft_send_bulk_cmd (self, cmd_fdt_sense, sizeof (cmd_fdt_sense));
      break;

    case FDT_STATE_WAIT_INTEGRATE:
      fpi_ssm_next_state_delayed (ssm, FDT_INTEGRATION_MS);
      break;

    case FDT_STATE_READ_CMD:
      {
        static const guint8 read_deltas_cmd[] = { 0x04, 0xFB, 0x80, 0xE8, 0x00, 0x04 };
        ft_send_bulk_cmd (self, read_deltas_cmd, sizeof (read_deltas_cmd));
      }
      break;

    case FDT_STATE_READ_DATA:
      {
        FpiUsbTransfer *rx = fpi_usb_transfer_new (FP_DEVICE (self));
        rx->ssm = ssm;
        fpi_usb_transfer_fill_bulk (rx, FT_EP_IN, 8);
        fpi_usb_transfer_submit (rx, 500, fpi_device_get_cancellable (FP_DEVICE (self)),
                                 fdt_read_cb, NULL);
      }
      break;
    }
}

static void
fdt_ssm_complete (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  self->active_ssm = NULL;
}

/* ========================================================================= */
/* Phase 2: Frame Capture & Normalization SSM (Reading from 0x0200)          */
/* ========================================================================= */

static void
capture_chunk_cb (FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (error)
    {
      fpi_ssm_mark_failed (transfer->ssm, error);
      return;
    }

  if (transfer->actual_length > 0)
    {
      memcpy (self->frame_buf + self->read_offset, transfer->buffer, transfer->actual_length);
      self->read_offset += transfer->actual_length;
    }

  if (self->read_offset >= RAW_BUF_SIZE)
    fpi_ssm_jump_to_state (transfer->ssm, CAP_STATE_PROCESS);
  else
    fpi_ssm_jump_to_state (transfer->ssm, CAP_STATE_READ_CHUNK);
}

static void
capture_ssm_state (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (self->deactivating)
    {
      fpi_ssm_mark_completed (ssm);
      return;
    }

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case CAP_STATE_PREPARE:
      {
        static const guint8 prep_pkt[] = {
          0x09, 0xF6, 0x9A, 0x00,
          0x5A, 0xA5, 0x00,
          0xA5, 0x5A, 0x00,
          0x05, 0xFA, 0x98, 0x01, 0x00, 0x01, 0xA7, 0xFC,
          0x05, 0xFA, 0x98, 0x00, 0x00, 0x01, 0xFE, 0x4F,
        };
        ft_send_bulk_cmd (self, prep_pkt, sizeof (prep_pkt));
      }
      break;

    case CAP_STATE_START:
      self->read_offset = 0;
      ft_send_bulk_cmd (self, cmd_scan_img, sizeof (cmd_scan_img));
      break;

    case CAP_STATE_WAIT:
      fpi_ssm_next_state_delayed (ssm, 40);
      break;

    case CAP_STATE_READ_CHUNK:
      {
        guint16 cur_addr = SRAM_FRAME_BASE + self->read_offset;
        guint8 sram_cmd[6] = {
          0x04, 0xFB,
          (guint8)(((cur_addr >> 8) | 0x80) & 0xFF),
          (guint8)(cur_addr & 0xFF),
          0x01, 0x00 /* 256 words = 512 bytes */
        };

        FpiUsbTransfer *tx = fpi_usb_transfer_new (FP_DEVICE (self));
        tx->ssm = ssm;
        fpi_usb_transfer_fill_bulk_full (tx, FT_EP_OUT, g_memdup2 (sram_cmd, 6), 6, g_free);
        fpi_usb_transfer_submit (tx, 500, fpi_device_get_cancellable (FP_DEVICE (self)),
                                 fpi_ssm_usb_transfer_cb, NULL);

        FpiUsbTransfer *rx = fpi_usb_transfer_new (FP_DEVICE (self));
        rx->ssm = ssm;
        fpi_usb_transfer_fill_bulk (rx, FT_EP_IN, 512);
        fpi_usb_transfer_submit (rx, 500, fpi_device_get_cancellable (FP_DEVICE (self)),
                                 capture_chunk_cb, NULL);
      }
      break;

    case CAP_STATE_PROCESS:
      {
        FpImage *img = fp_image_new (IMAGE_WIDTH, IMAGE_HEIGHT);
        img->ppmm = SENSOR_PPMM;
        img->flags = FPI_IMAGE_COLORS_INVERTED | FPI_IMAGE_PARTIAL;

        guint16 *pixels = g_malloc (RAW_PIXELS * sizeof (guint16));
        guint16 *sorted = g_malloc (RAW_PIXELS * sizeof (guint16));
        guint8 *raw_norm = g_malloc (RAW_PIXELS);

        for (int i = 0; i < RAW_PIXELS; i++)
          {
            guint16 px = (self->frame_buf[i * 2] << 8) | self->frame_buf[i * 2 + 1];
            pixels[i] = px;
            sorted[i] = px;
          }

        qsort (sorted, RAW_PIXELS, sizeof (guint16), compare_u16);
        guint16 p_low  = sorted[(RAW_PIXELS * 2) / 100];
        guint16 p_high = sorted[(RAW_PIXELS * 98) / 100];
        g_free (sorted);

        guint32 range = (p_high > p_low) ? (p_high - p_low) : 1;
        for (int i = 0; i < RAW_PIXELS; i++)
          {
            guint16 px = pixels[i];
            if (px < p_low) px = p_low;
            if (px > p_high) px = p_high;
            guint32 val = ((guint32)(px - p_low) * 255) / range;
            raw_norm[i] = (guint8) val;
          }
        g_free (pixels);

        /* 2x Bilinear upscaling to 128x160 for optimal NIST mindtct feature extraction */
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

        fp_dbg ("Captured frame from 0x0200: p_low=%d, p_high=%d, range=%d, dim=%dx%d, ppmm=%.2f",
                p_low, p_high, range, IMAGE_WIDTH, IMAGE_HEIGHT, img->ppmm);

        fpi_ssm_mark_completed (ssm);
        fpi_image_device_image_captured (FP_IMAGE_DEVICE (self), img);
      }
      break;
    }
}

static void
capture_ssm_complete (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  self->active_ssm = NULL;
}

/* ========================================================================= */
/* Phase 3: Wait Finger-Off SSM                                              */
/* ========================================================================= */

static void
finger_off_read_cb (FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (error)
    {
      fpi_ssm_mark_failed (transfer->ssm, error);
      return;
    }

  if (transfer->actual_length >= 8)
    {
      guint16 d0 = (transfer->buffer[0] << 8) | transfer->buffer[1];
      guint16 d1 = (transfer->buffer[2] << 8) | transfer->buffer[3];
      guint16 d2 = (transfer->buffer[4] << 8) | transfer->buffer[5];
      guint16 d3 = (transfer->buffer[6] << 8) | transfer->buffer[7];

      if (d0 < FDT_RELEASE_THRESHOLD && d1 < FDT_RELEASE_THRESHOLD &&
          d2 < FDT_RELEASE_THRESHOLD && d3 < FDT_RELEASE_THRESHOLD)
        {
          fp_dbg ("Finger lifted: [%d, %d, %d, %d]", d0, d1, d2, d3);
          fpi_ssm_mark_completed (transfer->ssm);
          fpi_image_device_report_finger_status (FP_IMAGE_DEVICE (self), FALSE);
          return;
        }
    }

  fpi_ssm_jump_to_state (transfer->ssm, OFF_STATE_WAIT_POLL);
}

static void
finger_off_ssm_state (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (self->deactivating)
    {
      fpi_ssm_mark_completed (ssm);
      return;
    }

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case OFF_STATE_WAIT_POLL:
      fpi_ssm_next_state_delayed (ssm, FDT_POLL_DELAY_MS);
      break;

    case OFF_STATE_SENSE:
      ft_send_bulk_cmd (self, cmd_fdt_sense, sizeof (cmd_fdt_sense));
      break;

    case OFF_STATE_WAIT_INTEGRATE:
      fpi_ssm_next_state_delayed (ssm, FDT_INTEGRATION_MS);
      break;

    case OFF_STATE_READ_CMD:
      {
        static const guint8 read_deltas_cmd[] = { 0x04, 0xFB, 0x80, 0xE8, 0x00, 0x04 };
        ft_send_bulk_cmd (self, read_deltas_cmd, sizeof (read_deltas_cmd));
      }
      break;

    case OFF_STATE_READ_DATA:
      {
        FpiUsbTransfer *rx = fpi_usb_transfer_new (FP_DEVICE (self));
        rx->ssm = ssm;
        fpi_usb_transfer_fill_bulk (rx, FT_EP_IN, 8);
        fpi_usb_transfer_submit (rx, 500, fpi_device_get_cancellable (FP_DEVICE (self)),
                                 finger_off_read_cb, NULL);
      }
      break;
    }
}

static void
finger_off_ssm_complete (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  self->active_ssm = NULL;
}

/* ========================================================================= */
/* Device Open / Close / Activate / Change State                             */
/* ========================================================================= */

static void
focaltech_dev_open (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  GError *error = NULL;

  g_usb_device_claim_interface (fpi_device_get_usb_device (FP_DEVICE (dev)), 0, 0, &error);
  if (error)
    {
      fpi_image_device_open_complete (dev, error);
      return;
    }

  self->frame_buf = g_malloc0 (RAW_BUF_SIZE);
  fpi_image_device_open_complete (dev, NULL);
  fp_dbg ("FocalTech 2808:6658 device opened");
}

static void
focaltech_dev_close (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  GError *error = NULL;

  g_clear_pointer (&self->frame_buf, g_free);
  g_usb_device_release_interface (fpi_device_get_usb_device (FP_DEVICE (dev)), 0, 0, &error);
  fpi_image_device_close_complete (dev, error);
  fp_dbg ("FocalTech 2808:6658 device closed");
}

static void
focaltech_dev_activate (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  self->deactivating = FALSE;
  fpi_image_device_activate_complete (dev, NULL);
}

static void
focaltech_dev_deactivate (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  self->deactivating = TRUE;
  if (self->active_ssm)
    {
      fpi_ssm_cancel_delayed_state_change (self->active_ssm);
      fpi_ssm_mark_completed (self->active_ssm);
      self->active_ssm = NULL;
    }
  fpi_image_device_deactivate_complete (dev, NULL);
}

static void
focaltech_dev_change_state (FpImageDevice *dev, FpiImageDeviceState state)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (self->deactivating)
    return;

  if (self->active_ssm)
    {
      fpi_ssm_cancel_delayed_state_change (self->active_ssm);
      fpi_ssm_mark_completed (self->active_ssm);
      self->active_ssm = NULL;
    }

  switch (state)
    {
    case FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_ON:
      self->active_ssm = fpi_ssm_new (FP_DEVICE (self), fdt_ssm_state, FDT_NUM_STATES);
      fpi_ssm_start (self->active_ssm, fdt_ssm_complete);
      break;

    case FPI_IMAGE_DEVICE_STATE_CAPTURE:
      self->active_ssm = fpi_ssm_new (FP_DEVICE (self), capture_ssm_state, CAP_NUM_STATES);
      fpi_ssm_start (self->active_ssm, capture_ssm_complete);
      break;

    case FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_OFF:
      self->active_ssm = fpi_ssm_new (FP_DEVICE (self), finger_off_ssm_state, OFF_NUM_STATES);
      fpi_ssm_start (self->active_ssm, finger_off_ssm_complete);
      break;

    case FPI_IMAGE_DEVICE_STATE_IDLE:
    case FPI_IMAGE_DEVICE_STATE_ACTIVATING:
    case FPI_IMAGE_DEVICE_STATE_DEACTIVATING:
    case FPI_IMAGE_DEVICE_STATE_INACTIVE:
    default:
      break;
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
  img_class->bz3_threshold = 12;
}
