import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const GET: RequestHandler = async ({ params }) => {
	const response = await fetch(`${BACKEND}/api/status/${params.id}`);
	const data = await response.json().catch(() => ({}));
	return json(data, { status: response.status });
};
