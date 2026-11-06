import "@testing-library/jest-dom/vitest";
import { useEffect, useRef } from "react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import {
  NotificationProvider,
  type Notification,
  useNotifications,
} from "@/contexts/NotificationContext";
import { NotificationBell } from "@/components/shell/NotificationBell";

type NotificationInput = Omit<Notification, "id" | "timestamp" | "read">;

function NotificationSeed({
  notifications,
}: {
  notifications: NotificationInput[];
}) {
  const { addNotification } = useNotifications();
  const seeded = useRef(false);

  useEffect(() => {
    if (seeded.current) {
      return;
    }

    seeded.current = true;
    notifications.forEach(addNotification);
  }, [addNotification, notifications]);

  return null;
}

function notification(
  number: number,
  action?: NotificationInput["action"],
): NotificationInput {
  return {
    title: `Notis ${number}`,
    message: `Meddelande ${number}`,
    type: "info",
    action,
  };
}

function renderNotificationBell(notifications: NotificationInput[] = []) {
  return render(
    <NotificationProvider>
      <NotificationSeed notifications={notifications} />
      <NotificationBell />
    </NotificationProvider>,
  );
}

function notificationTrigger() {
  return screen.getByRole("button", { name: "Notiser" });
}

function openNotifications() {
  fireEvent.click(notificationTrigger());
}

beforeAll(async () => {
  await import("@/i18n");
});

afterEach(() => {
  cleanup();
});

describe("NotificationBell", () => {
  it("shows the unread count in its Notiser trigger and omits a zero count", () => {
    renderNotificationBell();

    expect(
      within(notificationTrigger()).queryByText("0"),
    ).not.toBeInTheDocument();

    cleanup();
    renderNotificationBell([notification(1), notification(2)]);

    expect(within(notificationTrigger()).getByText("2")).toBeInTheDocument();
  });

  it("opens an empty popover and closes it with Stäng", async () => {
    renderNotificationBell();

    openNotifications();

    expect(
      screen
        .getAllByText("Notiser")
        .some((element) => !element.closest("button")),
    ).toBe(true);
    expect(screen.getByText("Inga notifieringar än")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Markera alla som lästa" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Stäng" }));

    await waitFor(() => {
      expect(
        screen.queryByText("Inga notifieringar än"),
      ).not.toBeInTheDocument();
    });
  });

  it("renders the newest eight unread notifications with their messages", () => {
    renderNotificationBell(
      Array.from({ length: 9 }, (_, index) => notification(index + 1)),
    );

    openNotifications();

    expect(
      screen.getAllByText(/^Notis \d+$/).map((element) => element.textContent),
    ).toEqual([
      "Notis 9",
      "Notis 8",
      "Notis 7",
      "Notis 6",
      "Notis 5",
      "Notis 4",
      "Notis 3",
      "Notis 2",
    ]);
    expect(
      screen
        .getAllByText(/^Meddelande \d+$/)
        .map((element) => element.textContent),
    ).toEqual([
      "Meddelande 9",
      "Meddelande 8",
      "Meddelande 7",
      "Meddelande 6",
      "Meddelande 5",
      "Meddelande 4",
      "Meddelande 3",
      "Meddelande 2",
    ]);
    expect(screen.queryByText("Notis 1")).not.toBeInTheDocument();
    expect(
      screen.getByText("Notis 9").closest('[class*="unread"]'),
    ).not.toBeNull();
  });

  it("marks a clicked unread notification as read and decreases the badge", () => {
    renderNotificationBell([notification(1), notification(2)]);

    expect(within(notificationTrigger()).getByText("2")).toBeInTheDocument();

    openNotifications();

    const unreadRow = screen.getByText("Notis 2").closest('[class*="unread"]');
    expect(unreadRow).not.toBeNull();

    fireEvent.click(unreadRow!);

    expect(within(notificationTrigger()).getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Notis 2").closest('[class*="unread"]')).toBeNull();
  });

  it("renders a notification action with an href as a link", () => {
    renderNotificationBell([
      notification(1, {
        label: "Öppna notis",
        href: "/stamboken/alla-kaniner/G1274-2301",
      }),
    ]);

    openNotifications();

    expect(
      screen
        .getAllByRole("link")
        .some(
          (link) =>
            link.getAttribute("href") === "/stamboken/alla-kaniner/G1274-2301",
        ),
    ).toBe(true);
  });

  it("marks all notifications as read and then hides the mark-all button", () => {
    renderNotificationBell([notification(1), notification(2)]);

    openNotifications();
    fireEvent.click(
      screen.getByRole("button", { name: "Markera alla som lästa" }),
    );

    expect(
      within(notificationTrigger()).queryByText(/^\d+$/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Markera alla som lästa" }),
    ).not.toBeInTheDocument();
  });
});
