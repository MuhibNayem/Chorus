import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const GET: RequestHandler = async ({ params, url }) => {
	const projectId = params.id;
	const limit = url.searchParams.get('limit') || '25';

	const response = await fetch(`${BACKEND}/api/projects/${projectId}/checkpoints?limit=${limit}`);
	const data = await response.json();
	return json(data);
};