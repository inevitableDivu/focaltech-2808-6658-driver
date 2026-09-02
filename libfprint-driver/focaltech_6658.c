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

#define SENSOR_WIDTH   64
#define SENSOR_HEIGHT  80
#define SENSOR_PIXELS  (SENSOR_WIDTH * SENSOR_HEIGHT)
#define SENSOR_RAW_LEN (SENSOR_PIXELS * 2)

#define FDT_TOUCH_THRESHOLD 50

/* USB command packets */
static const guint8 cmd_reset[]     = { 0xC0, 0x3F, 0x00 };
static const guint8 cmd_fdt_sense[] = { 0xC2, 0x3D, 0x00 };
static const guint8 cmd_scan_img[]  = { 0xC4, 0x3B, 0x00 };
static const guint8 cmd_afe_wake[]  = { 0x5A, 0xA5, 0x00 };
static const guint8 cmd_afe_lock[]  = { 0xA5, 0x5A, 0x00 };

/* Loop SSM states */
enum {
  STATE_FDT_SENSE,
  STATE_FDT_READ_DELTAS,
  STATE_CAPTURE_START,
  STATE_CAPTURE_WAIT,
  STATE_CAPTURE_READ_SRAM,
  STATE_FINGER_OFF_POLL,
  NUM_STATES,
};

struct _FpiDeviceFocaltech6658
{
  FpImageDevice parent;
  FpiSsm       *ssm;
  guint8       *frame_buf;
  gboolean      deactivating;
  GCancellable *cancellable;
  GSource      *poll_timer;
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
ft_write_reg_sync (FpiDeviceFocaltech6658 *self, guint8 reg, guint8 val)
{
  FpiUsbTransfer *transfer;
  guint8 *buf = g_malloc (4);

  buf[0] = 0x09;
  buf[1] = 0xF6;
  buf[2] = reg;
  buf[3] = val;

  transfer = fpi_usb_transfer_new (FP_DEVICE (self));
  fpi_usb_transfer_fill_bulk_full (transfer, FT_EP_OUT, buf, 4, g_free);
  fpi_usb_transfer_submit_sync (transfer, 1000, NULL);
}

static void
ft_write_16bit_sync (FpiDeviceFocaltech6658 *self, guint16 addr, guint16 val)
{
  FpiUsbTransfer *transfer;
  guint8 *buf = g_malloc (8);

  buf[0] = 0x05;
  buf[1] = 0xFA;
  buf[2] = ((addr >> 8) | 0x80) & 0xFF;
  buf[3] = addr & 0xFF;
  buf[4] = 0x00;
  buf[5] = 0x01;
  buf[6] = val & 0xFF;
  buf[7] = (val >> 8) & 0xFF;

  transfer = fpi_usb_transfer_new (FP_DEVICE (self));
  fpi_usb_transfer_fill_bulk_full (transfer, FT_EP_OUT, buf, 8, g_free);
  fpi_usb_transfer_submit_sync (transfer, 1000, NULL);
}

static void
ft_send_cmd_sync (FpiDeviceFocaltech6658 *self, const guint8 *cmd, gsize len)
{
  FpiUsbTransfer *transfer;

  transfer = fpi_usb_transfer_new (FP_DEVICE (self));
  fpi_usb_transfer_fill_bulk (transfer, FT_EP_OUT, len);
  memcpy (transfer->buffer, cmd, len);
  fpi_usb_transfer_submit_sync (transfer, 1000, NULL);
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
      fpi_image_device_open_complete (dev, error);
      return;
    }

  self->frame_buf = g_malloc0 (SENSOR_RAW_LEN);

  /* Initialize AFE and hardware registers */
  ft_write_reg_sync (self, 0xC6, 0x00);
  g_usleep (10000);
  ft_send_cmd_sync (self, cmd_afe_wake, sizeof (cmd_afe_wake));
  g_usleep (10000);
  ft_send_cmd_sync (self, cmd_afe_lock, sizeof (cmd_afe_lock));
  g_usleep (10000);

  fp_dbg ("FocalTech 2808:6658 initialized successfully");
  fpi_image_device_open_complete (dev, NULL);
}

/* Close sequence */
static void
focaltech_dev_close (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  GError *error = NULL;

  ft_send_cmd_sync (self, cmd_reset, sizeof (cmd_reset));
  g_free (self->frame_buf);
  self->frame_buf = NULL;

  g_usb_device_release_interface (fpi_device_get_usb_device (FP_DEVICE (dev)), 0, 0, &error);
  fpi_image_device_close_complete (dev, error);
}

/* Activate */
static void
focaltech_dev_activate (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  self->deactivating = FALSE;
  ft_write_reg_sync (self, 0x9A, 0x5A); /* Enable FDT mode */

  fpi_image_device_activate_complete (dev, NULL);
}

/* Deactivate */
static void
focaltech_dev_deactivate (FpImageDevice *dev)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  self->deactivating = TRUE;
  if (self->poll_timer)
    {
      g_source_destroy (self->poll_timer);
      self->poll_timer = NULL;
    }

  ft_write_reg_sync (self, 0x9A, 0x00); /* Disable FDT mode */
  fpi_image_device_deactivate_complete (dev, NULL);
}

/* Capture / State handler */
static gboolean
poll_finger_touch (gpointer user_data)
{
  FpImageDevice *dev = FP_IMAGE_DEVICE (user_data);
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);
  FpiUsbTransfer *transfer;
  guint8 *sram_cmd;
  GError *error = NULL;

  if (self->deactivating)
    return G_SOURCE_REMOVE;

  /* Trigger FDT Sense */
  ft_send_cmd_sync (self, cmd_fdt_sense, sizeof (cmd_fdt_sense));
  g_usleep (5000);

  /* Read 8 bytes from SRAM 0x00E8 (Touch Deltas) */
  sram_cmd = g_malloc (6);
  sram_cmd[0] = 0x04;
  sram_cmd[1] = 0xFB;
  sram_cmd[2] = 0x80;
  sram_cmd[3] = 0xE8;
  sram_cmd[4] = 0x00;
  sram_cmd[5] = 0x04; /* 4 words = 8 bytes */

  transfer = fpi_usb_transfer_new (FP_DEVICE (self));
  fpi_usb_transfer_fill_bulk_full (transfer, FT_EP_OUT, sram_cmd, 6, g_free);
  fpi_usb_transfer_submit_sync (transfer, 500, &error);

  if (!error)
    {
      guint8 deltas_buf[8] = { 0 };
      transfer = fpi_usb_transfer_new (FP_DEVICE (self));
      fpi_usb_transfer_fill_bulk (transfer, FT_EP_IN, 8);
      fpi_usb_transfer_submit_sync (transfer, 500, &error);

      if (!error && transfer->actual_length == 8)
        {
          memcpy (deltas_buf, transfer->buffer, 8);
          guint16 d0 = (deltas_buf[0] << 8) | deltas_buf[1];
          guint16 d1 = (deltas_buf[2] << 8) | deltas_buf[3];
          guint16 d2 = (deltas_buf[4] << 8) | deltas_buf[5];
          guint16 d3 = (deltas_buf[6] << 8) | deltas_buf[7];

          if (d0 > FDT_TOUCH_THRESHOLD || d1 > FDT_TOUCH_THRESHOLD ||
              d2 > FDT_TOUCH_THRESHOLD || d3 > FDT_TOUCH_THRESHOLD)
            {
              fp_dbg ("Finger touch detected: [%d, %d, %d, %d]", d0, d1, d2, d3);
              self->poll_timer = NULL;
              fpi_image_device_report_finger_status (dev, TRUE);
              return G_SOURCE_REMOVE;
            }
        }
    }

  return G_SOURCE_CONTINUE;
}

static void
focaltech_change_state (FpImageDevice *dev, FpiImageDeviceState state)
{
  FpiDeviceFocaltech6658 *self = FPI_DEVICE_FOCALTECH_6658 (dev);

  if (self->deactivating)
    return;

  switch (state)
    {
    case FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_ON:
      ft_write_reg_sync (self, 0x9A, 0x5A); /* Enable FDT */
      if (!self->poll_timer)
        self->poll_timer = g_timeout_source_new (100);
      g_source_set_callback (self->poll_timer, poll_finger_touch, dev, NULL);
      g_source_attach (self->poll_timer, fpi_device_get_main_context (FP_DEVICE (dev)));
      break;

    case FPI_IMAGE_DEVICE_STATE_CAPTURE:
      {
        ft_write_reg_sync (self, 0x9A, 0x00); /* Disable FDT */
        ft_write_16bit_sync (self, 0x1801, 0xFCA7);
        ft_write_16bit_sync (self, 0x1800, 0x4FFE);
        g_usleep (5000);

        /* Trigger Image Scan */
        ft_send_cmd_sync (self, cmd_scan_img, sizeof (cmd_scan_img));
        g_usleep (40000);

        /* Read 10,240 bytes from SRAM 0x0000 in 512-byte chunks */
        gsize offset = 0;
        while (offset < SENSOR_RAW_LEN)
          {
            guint16 cur_addr = offset;
            guint8 sram_cmd[6];
            sram_cmd[0] = 0x04;
            sram_cmd[1] = 0xFB;
            sram_cmd[2] = ((cur_addr >> 8) | 0x80) & 0xFF;
            sram_cmd[3] = cur_addr & 0xFF;
            sram_cmd[4] = 0x01; /* 256 words = 512 bytes */
            sram_cmd[5] = 0x00;

            FpiUsbTransfer *tx = fpi_usb_transfer_new (FP_DEVICE (self));
            fpi_usb_transfer_fill_bulk (tx, FT_EP_OUT, 6);
            memcpy (tx->buffer, sram_cmd, 6);
            fpi_usb_transfer_submit_sync (tx, 500, NULL);

            FpiUsbTransfer *rx = fpi_usb_transfer_new (FP_DEVICE (self));
            fpi_usb_transfer_fill_bulk (rx, FT_EP_IN, 512);
            fpi_usb_transfer_submit_sync (rx, 500, NULL);
            if (rx->actual_length > 0)
              {
                memcpy (self->frame_buf + offset, rx->buffer, rx->actual_length);
                offset += rx->actual_length;
              }
            else
              {
                break;
              }
          }

        /* Create FpImage and normalize 16-bit to 8-bit */
        FpImage *img = fp_image_new (SENSOR_WIDTH, SENSOR_HEIGHT);
        img->flags |= FPI_IMAGE_COLORS_INVERTED;

        guint16 min_v = 65535, max_v = 0;
        guint16 *pixels = (guint16 *) g_malloc (SENSOR_PIXELS * sizeof (guint16));

        for (int i = 0; i < SENSOR_PIXELS; i++)
          {
            guint16 px = (self->frame_buf[i * 2] << 8) | self->frame_buf[i * 2 + 1];
            pixels[i] = px;
            if (px < min_v) min_v = px;
            if (px > max_v) max_v = px;
          }

        guint32 range = (max_v > min_v) ? (max_v - min_v) : 1;
        for (int i = 0; i < SENSOR_PIXELS; i++)
          {
            guint32 val = ((guint32)(pixels[i] - min_v) * 255) / range;
            img->data[i] = (guint8) val;
          }
        g_free (pixels);

        fp_dbg ("Captured frame: min=%d, max=%d, range=%d", min_v, max_v, range);
        fpi_image_device_image_captured (dev, img);
      }
      break;

    case FPI_IMAGE_DEVICE_STATE_AWAIT_FINGER_OFF:
      fpi_image_device_report_finger_status (dev, FALSE);
      break;

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
  img_class->change_state = focaltech_change_state;

  img_class->img_width = SENSOR_WIDTH;
  img_class->img_height = SENSOR_HEIGHT;
  img_class->bz3_threshold = 20;
}
