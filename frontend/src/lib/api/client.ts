// Base fetch wrapper: consistent error handling for every API call.
// Resource-specific files (e.g. rules.ts) call this instead of using
// fetch() directly.
import { API_BASE } from '$lib/config/env';

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

export async function apiGet<T>(path: string, params?: Record<string, string | number>): Promise<T> {
	const url = new URL(`${API_BASE}${path}`);
	if (params) {
		for (const [key, value] of Object.entries(params)) {
			url.searchParams.set(key, String(value));
		}
	}
	const res = await fetch(url);
	if (!res.ok) {
		throw new ApiError(res.status, `${path} failed with ${res.status}`);
	}
	return res.json();
}

export async function apiPost<T>(path: string, body: Record<string, unknown>): Promise<T> {
	const res = await fetch(`${API_BASE}${path}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!res.ok) {
		throw new ApiError(res.status, `${path} failed with ${res.status}`);
	}
	return res.json();
}