import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const GET: RequestHandler = async ({ params, url }) => {
	const projectId = params.project_id;
	const message = url.searchParams.get('message') || '';

	const backendUrl = `${BACKEND}/api/stream/${projectId}?message=${encodeURIComponent(message)}`;

	const response = await fetch(backendUrl, {
		headers: {
			Accept: 'text/event-stream'
		}
	});

	if (!response.ok) {
		return new Response('Backend error', { status: 502 });
	}

	const stream = response.body;

	if (!stream) {
		return new Response('No stream', { status: 500 });
	}

	return new Response(stream, {
		headers: {
			'Content-Type': 'text/event-stream',
			'Cache-Control': 'no-cache',
			'Connection': 'keep-alive'
		}
	});
};
