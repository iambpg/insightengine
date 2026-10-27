'use client';

import React from 'react';
import { Toaster } from 'sonner';

export default function ToastHost() {
  return <Toaster position="bottom-right" richColors closeButton duration={3000} />;
}