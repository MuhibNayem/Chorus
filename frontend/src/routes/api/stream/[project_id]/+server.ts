import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const BACKEND = env.BACKEND_URL || 'http://localhost:8000';

export const GET: RequestHandler = async ({ params, url, request }) => {
	const projectId = params.project_id;
	const paramsOut = new URLSearchParams();
	const contextMode = url.searchParams.get('context_mode');
	const mode = url.searchParams.get('mode');
	const uiMode = url.searchParams.get('ui_mode');

	if (contextMode) paramsOut.set('context_mode', contextMode);
	if (mode) paramsOut.set('mode', mode);
	if (uiMode) paramsOut.set('ui_mode', uiMode);

	const query = paramsOut.toString();
	const backendUrl = query
		? `${BACKEND}/api/stream/${projectId}?${query}`
		: `${BACKEND}/api/stream/${projectId}`;

	const response = await fetch(backendUrl, {
		signal: request.signal,
		headers: {
			Accept: 'text/event-stream',
			'Cache-Control': 'no-cache'
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
			'Cache-Control': 'no-cache, no-transform',
			'Connection': 'keep-alive',
			'X-Accel-Buffering': 'no'
		}
	});
};
