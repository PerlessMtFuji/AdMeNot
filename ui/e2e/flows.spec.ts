import { expect, type Page, test } from '@playwright/test';

async function scan(page: Page, scenario: string) {
  await page.goto(`/?scenario=${scenario}`);
  await expect(page.getByText('Telefon gotowy')).toBeVisible();
  await page.getByPlaceholder('np. Anna K.').fill('Anna K.');
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByText('Przedmiot zlecenia')).toBeVisible();
  await expect(page.getByText(/Analiza APK w tle/)).toBeHidden({ timeout: 15_000 });
}

test('adware: scan, fix with the admin step, undo from history', async ({ page }) => {
  await scan(page, 'adware');
  await expect(page.getByText(/Aplikacje, które zaśmiecają telefon/)).toBeVisible();
  await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
  await expect(page.getByRole('dialog', { name: 'Plan naprawy' })).toBeVisible();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByText(/ZS\/2026\/0926\/01: wykonane/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('✓ Gotowe')).toHaveCount(2);
  await page.getByRole('button', { name: 'Cofnij całe zlecenie' }).click();
  await expect(page.getByText(/ZS\/2026\/0926\/01: cofnięte/).first()).toBeVisible({ timeout: 15_000 });
});

test('clean phone has nothing to fix', async ({ page }) => {
  await scan(page, 'clean');
  await expect(page.getByText(/Nie znaleziono podejrzanych aplikacji/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Napraw zaznaczone (0)' })).toBeDisabled();
});

test('disconnect during the order, then finish it', async ({ page }) => {
  await scan(page, 'disconnect');
  await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByText(/Telefon odłączony w trakcie zlecenia/)).toBeVisible({ timeout: 15_000 });
  await page.getByRole('button', { name: 'Dokończ' }).click();
  await expect(page.getByText(/: wykonane/)).toBeVisible({ timeout: 15_000 });
});

test('unauthorized phone shows the prompt hint', async ({ page }) => {
  await page.goto('/?scenario=unauthorized');
  await expect(page.getByText(/nieautoryzowany/)).toBeVisible();
});

test('expert mode and English', async ({ page }) => {
  await scan(page, 'adware');
  await page.getByRole('button', { name: 'Ekspert' }).click();
  await expect(page.getByRole('columnheader', { name: 'Aplikacja / pakiet' })).toBeVisible();
  await page.getByRole('combobox', { name: 'Język' }).selectOption('en');
  await expect(page.getByRole('button', { name: /Fix selected/ })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'App / package' })).toBeVisible();
});
