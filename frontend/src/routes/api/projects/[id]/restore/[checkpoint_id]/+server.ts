import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const POST: RequestHandler = async ({ params }) => {
	const projectId = params.id;
	const checkpointId = params.checkpoint_id;

	const response = await fetch(`${BACKEND}/api/projects/${projectId}/restore/${checkpointId}`, {
		method: 'POST'
	});
	const data = await response.json();
	return json(data, { status: response.status });
};
