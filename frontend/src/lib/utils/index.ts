import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

export type WithElementRef<T> = T & { ref?: HTMLElement | null | undefined };
export type WithoutChild<T> = T & { children?: undefined };
export type WithoutChildren<T> = WithoutChild<T>;
