import { test, expect, type Page } from '@playwright/test'
async function login(page: Page, listener: string) {
  await page.getByRole('button', { name: listener }).click()
  await expect(
    page.getByRole('heading', { name: "Today's news." }),
  ).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Choose your voice' }),
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Discussion model' }),
  ).toHaveCount(0)
  return page.evaluate(async () => {
    const response = await fetch('/api/v1/recommendations?period=week', {
      headers: {
        Authorization: 'Bearer ' + sessionStorage.getItem('sourcera.session'),
      },
    })
    return (await response.json())[0].title as string
  })
}
test('two listeners can generate and hear a source-grounded synthetic edition', async ({
  page,
}) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new DOMException(
        'Microphone disabled in playback test',
        'NotAllowedError',
      )
    }
  })
  await page.goto('/')
  const firstA = await login(page, 'Technology enthusiast')
  await expect(
    page.getByRole('button', { name: 'Play daily briefing', exact: true }),
  ).toBeEnabled({ timeout: 120000 })
  let generations = 0
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().endsWith('/api/v1/briefings'))
      generations++
  })
  await page
    .getByRole('button', { name: 'Play daily briefing', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Pause daily briefing', exact: true }),
  ).toBeVisible()
  expect(generations).toBe(0)
  await page
    .getByRole('button', { name: 'Pause daily briefing', exact: true })
    .click()
  await page.getByRole('button', { name: 'Street Signal', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Street Signal', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(
    page.getByRole('button', { name: 'Create with this voice' }),
  ).toBeVisible()
  expect(generations).toBe(0)
  await page.getByRole('button', { name: /This week/ }).click()
  await expect(page.getByRole('heading', { name: 'This week.' })).toBeVisible({
    timeout: 120000,
  })
  await expect(
    page.getByRole('button', { name: 'Pause daily briefing', exact: true }),
  ).toBeVisible({ timeout: 120000 })
  await page
    .getByRole('button', { name: 'Pause daily briefing', exact: true })
    .click()
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await page.getByRole('tab', { name: /Voice & language/ }).click()
  await page.getByText('Fine-tune your assistant', { exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Assistant model', exact: true })
    .selectOption('grounded')
  await page.getByRole('button', { name: 'Save preferences' }).click()
  await expect(
    page.getByText('Preferences saved.', { exact: true }),
  ).toBeVisible()
  await page.getByRole('link', { name: 'Listening room', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Street Signal', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(
    page.getByRole('button', { name: 'Play daily briefing', exact: true }),
  ).toBeEnabled({ timeout: 120000 })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: test.info().outputPath('dashboard-desktop.png'),
    fullPage: true,
  })
  await page
    .getByRole('link', { name: 'Explore stories', exact: true })
    .first()
    .click()
  await page
    .getByRole('textbox', { name: 'Search stories' })
    .or(page.getByRole('searchbox', { name: 'Search stories' }))
    .fill(firstA)
  await page.locator('.story-card').first().click()
  await expect(
    page.getByRole('heading', { name: 'Facts and evidence' }),
  ).toBeVisible()
  await page.locator('details').first().locator('summary').click()
  await expect(page.locator('.citation').first()).toBeVisible()
  await page.getByRole('link', { name: 'Make a briefing' }).click()
  await page.getByRole('button', { name: 'Generate audio briefing' }).click()
  await expect(page.getByRole('button', { name: 'Play audio' })).toBeEnabled({
    timeout: 90000,
  })
  await page.getByRole('button', { name: 'Play audio' }).click()
  await expect(page.getByRole('button', { name: 'Pause audio' })).toBeVisible()
  await expect(page.locator('.transcript .citation').first()).toBeAttached()
  await expect(
    page.getByText(
      'AI-generated narration. All factual claims are linked to their sources.',
    ),
  ).toBeVisible()
  await page.getByRole('link', { name: 'Discuss this briefing' }).click()
  await page.getByText('Type a question', { exact: true }).click()
  await page
    .getByRole('textbox', { name: 'Your question' })
    .fill('What do other sources say?')
  await page.getByRole('button', { name: 'Send question' }).click()
  await expect(page.locator('.voice-conversation audio')).toHaveJSProperty(
    'paused',
    false,
  )
  await expect(page.locator('.chat-message')).toHaveCount(0)
  await page.getByRole('link', { name: 'Transparency', exact: true }).click()
  await expect(
    page.getByText('Simulated cost at 10× dataset volume'),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Switch listener' }).click()
  const firstB = await login(page, 'Financial analyst')
  expect(firstB).not.toEqual(firstA)
  await expect(
    page.getByRole('button', { name: 'Play daily briefing', exact: true }),
  ).toBeEnabled({ timeout: 120000 })
  await page
    .getByRole('button', { name: 'Play daily briefing', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Pause daily briefing', exact: true }),
  ).toBeVisible()
})
test('arbitrary listener can complete onboarding and schedule a briefing on mobile', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Register', exact: true }).click()
  await page.getByLabel('Name', { exact: true }).fill('Science listener')
  await page
    .getByLabel('Email', { exact: true })
    .fill('listener-' + crypto.randomUUID() + '@example.com')
  await page.getByLabel('Password', { exact: true }).fill('SyntheticDemo57235!')
  await page.getByRole('button', { name: 'Create profile' }).click()
  await expect(
    page.getByRole('heading', { name: 'Tune your briefing' }),
  ).toBeVisible()
  await page.getByRole('button', { name: 'Add your own topic' }).click()
  await page.getByPlaceholder('Enter a topic').fill('low carbon science')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByRole('tab', { name: /Daily routine/ }).click()
  await page.getByLabel('Daily briefing', { exact: false }).check()
  await page.getByLabel('Delivery time', { exact: true }).fill('10:20')
  await page.getByRole('button', { name: 'Finish setup' }).click()
  await expect(
    page.getByRole('heading', { name: "Today's news." }),
  ).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Choose your voice' }),
  ).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: test.info().outputPath('dashboard-mobile.png'),
    fullPage: true,
  })
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Low carbon science' }),
  ).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('tab', { name: /Daily routine/ }).click()
  await expect(page.getByLabel('Delivery time', { exact: true })).toHaveValue(
    '10:20',
  )
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth,
  )
  expect(overflow).toBe(false)
})

test('voice clicks and settings navigation keep the shell and prepared audio stable', async ({
  page,
}) => {
  await page.goto('/')
  await login(page, 'Technology enthusiast')
  await expect(
    page.getByRole('button', { name: 'Play daily briefing', exact: true }),
  ).toBeEnabled({ timeout: 120000 })
  const originalAudio = await page.locator('audio').first().getAttribute('src')
  const originalTimeOrigin = await page.evaluate(() => performance.timeOrigin)
  await page
    .locator('.music-header')
    .evaluate((el) => el.setAttribute('data-continuity', 'retained'))
  let audioFetches = 0
  let documentRequests = 0
  page.on('request', (req) => {
    if (req.resourceType() === 'document') documentRequests++
    if (req.url().includes('/briefings/') && req.url().endsWith('/audio'))
      audioFetches++
  })
  await page.route('**/api/v1/users/me/preferences', async (route) => {
    if (route.request().method() === 'PATCH')
      await new Promise((resolve) => setTimeout(resolve, 400))
    await route.continue()
  })
  const hero = page.getByRole('region', { name: 'News player' })
  const before = await hero.boundingBox()
  await page.getByRole('button', { name: 'Street Signal', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Street Signal', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  expect(
    await page
      .locator('.music-host')
      .evaluateAll((buttons) =>
        buttons.every((button) => getComputedStyle(button).opacity === '1'),
      ),
  ).toBe(true)
  expect(await page.locator('audio').first().getAttribute('src')).toBe(
    originalAudio,
  )
  await expect(
    page.getByRole('button', { name: 'Create with this voice' }),
  ).toBeVisible()
  expect(await hero.boundingBox()).toEqual(before)
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Listening preferences' }),
  ).toBeVisible()
  await expect(page.locator('.music-header')).toHaveAttribute(
    'data-continuity',
    'retained',
  )
  await page.getByRole('link', { name: 'Listening room', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Play daily briefing', exact: true }),
  ).toBeEnabled()
  expect(await page.locator('audio').first().getAttribute('src')).toBe(
    originalAudio,
  )
  await expect(page.locator('.music-header')).toHaveAttribute(
    'data-continuity',
    'retained',
  )
  expect(audioFetches).toBe(0)
  expect(documentRequests).toBe(0)
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(
    originalTimeOrigin,
  )
})

test('preferences stay focused with many sources and preserve edits between sections', async ({
  page,
}) => {
  await page.goto('/')
  await login(page, 'Technology enthusiast')
  const sources = Array.from({ length: 31 }, (_, i) => ({
    id: 'publication-' + i,
    name: `Publication ${String(i + 1).padStart(2, '0')}`,
    is_synthetic: false,
  }))
  await page.route('**/api/v1/sources', (route) =>
    route.fulfill({ json: sources }),
  )
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await page.getByRole('tab', { name: /Sources/ }).click()
  await expect(page.locator('.preference-source')).toHaveCount(7)
  await expect(page.getByText('1–7 of 31 sources')).toBeVisible()
  await page.getByRole('button', { name: 'Next sources' }).click()
  await expect(page.getByText('8–14 of 31 sources')).toBeVisible()
  await page
    .getByRole('searchbox', { name: 'Search sources' })
    .fill('Publication 30')
  await expect(page.locator('.preference-source')).toHaveCount(1)
  await page.getByLabel('Publication 30 preference').selectOption('prefer')
  await expect(page.getByText('Unsaved changes', { exact: true })).toBeVisible()
  await page.getByRole('tab', { name: /Voice & language/ }).click()
  await page.getByRole('button', { name: 'DE German', exact: true }).click()
  await page.getByRole('tab', { name: /Sources/ }).click()
  await expect(page.getByLabel('Publication 30 preference')).toHaveValue(
    'prefer',
  )
  await page.getByRole('button', { name: 'Preferred', exact: true }).click()
  await expect(page.locator('.preference-source')).toHaveCount(1)
  await page.getByRole('button', { name: 'Discard', exact: true }).click()
  await expect(page.getByText('No matching publications')).toBeVisible()
  await page.getByRole('button', { name: 'Show all sources' }).click()
  await expect(page.locator('.preference-source')).toHaveCount(7)
  await page
    .getByRole('searchbox', { name: 'Search sources' })
    .fill('nothing-matches')
  await expect(page.getByText('No matching publications')).toBeVisible()
  await page.setViewportSize({ width: 360, height: 780 })
  await page.getByRole('tab', { name: /Daily routine/ }).click()
  await expect(
    page.getByRole('heading', { name: 'A moment for the world.' }),
  ).toBeVisible()
  await page.getByRole('tab', { name: /Daily routine/ }).press('ArrowRight')
  await expect(page.getByRole('tab', { name: /Sources/ })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false)
})

test('muting input preserves narration and spoken additional news without showing answer text', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const state = window as unknown as {
      micRequests: number
      micTracks: MediaStreamTrack[]
    }
    state.micRequests = 0
    state.micTracks = []
    navigator.mediaDevices.getUserMedia = async () => {
      state.micRequests++
      const context = new AudioContext()
      await context.resume()
      const destination = context.createMediaStreamDestination()
      const oscillator = context.createOscillator(),
        gain = context.createGain()
      gain.gain.value = 0
      oscillator.connect(gain).connect(destination)
      oscillator.start()
      const tracks = destination.stream.getTracks()
      state.micTracks.push(...tracks)
      return destination.stream
    }
  })
  await page.goto('/')
  await login(page, 'Technology enthusiast')
  const play = page.getByRole('button', {
    name: 'Play daily briefing',
    exact: true,
  })
  await expect(play).toBeEnabled({ timeout: 120000 })
  await play.click()
  expect(
    await page.evaluate(
      () => (window as unknown as { micRequests: number }).micRequests,
    ),
  ).toBe(0)
  await page.getByRole('button', { name: 'Turn microphone on' }).click()
  await page.getByRole('button', { name: 'Turn microphone off' }).click()
  await expect(page.locator('.listening-hero audio').first()).toHaveJSProperty(
    'paused',
    false,
  )
  expect(
    await page.evaluate(() =>
      (window as unknown as { micTracks: MediaStreamTrack[] }).micTracks.every(
        (t) => t.readyState === 'ended',
      ),
    ),
  ).toBe(true)
  await page.getByRole('button', { name: 'More news', exact: true }).click()
  const spoken = page.locator('.listening-hero audio').nth(1)
  await expect(spoken).toHaveJSProperty('paused', false)
  await expect(page.locator('.live-response')).toHaveCount(0)
  await page.getByRole('button', { name: 'Turn microphone on' }).click()
  await page.getByRole('button', { name: 'Turn microphone off' }).click()
  const time = await spoken.evaluate((a: HTMLAudioElement) => a.currentTime)
  await expect(async () =>
    expect(
      await spoken.evaluate((a: HTMLAudioElement) => a.currentTime),
    ).toBeGreaterThan(time + 0.2),
  ).toPass({ timeout: 5000 })
  await expect(spoken).toHaveJSProperty('paused', false)
})
