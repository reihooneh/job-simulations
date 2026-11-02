# Commonwealth Bank: Software Engineering Job Simulation

**Platform:** [Forage](https://www.theforage.com/) · **Completed:** November 2026 · **Level:** Advanced (5 tasks)

**Stack:**

![C#](https://img.shields.io/badge/C%23-.NET%206-512BD4?logo=dotnet)
![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb&logoColor=white)
![React](https://img.shields.io/badge/React-17-61DAFB?logo=react&logoColor=black)
![Redux](https://img.shields.io/badge/Redux-Toolkit-764ABC?logo=redux)
![TypeScript](https://img.shields.io/badge/TypeScript-4.7-3178C6?logo=typescript&logoColor=white)
![xUnit](https://img.shields.io/badge/Tests-xUnit-5C2D91)

In this simulation I joined Commonwealth Bank's engineering team working on the **CommBank Goal Tracker**, a full-stack app where customers set savings goals and track their progress. My feature was **goal icons**: customers can give each savings goal an emoji (🏠 for a house deposit, ✈️ for a holiday) so their goals are easier to recognise at a glance.

I shipped the feature end to end, across the C# backend, the MongoDB data model, the React and Redux frontend, the API integration, unit tests and a git pull request.

---

## The five tasks

| # | Task | What I did | Key files |
| --- | --- | --- | --- |
| 1 | **Modify an existing .NET backend** | Added an optional `Icon` field to the `Goal` model and tested the API manually with Postman | [`Goal.cs`](server/CommBank-Server/Models/Goal.cs) |
| 2 | **Modify an existing React/Redux frontend** | Added the icon to the client type, showed it on goal cards, built the "Add icon" button and emoji picker, and updated the Redux store | [`GoalManager.tsx`](web/src/ui/features/goalmanager/GoalManager.tsx), [`GoalCard.tsx`](web/src/ui/pages/Main/goals/GoalCard.tsx), [`types.ts`](web/src/api/types.ts) |
| 3 | **Modify the client's requests** | Connected the emoji picker to the API with an Axios `PUT` request, so icons stay after a refresh | [`GoalManager.tsx`](web/src/ui/features/goalmanager/GoalManager.tsx), [`lib.ts`](web/src/api/lib.ts) |
| 4 | **Cover your code** | Wrote an xUnit test for the `GetForUser` route | [`GoalControllerTests.cs`](server/CommBank.Tests/GoalControllerTests.cs) |
| 5 | **Create a pull request** | Branched (`icons`), committed and packaged the change as a patch for review | [`support-icons.patch`](support-icons.patch) |

---

## How the feature works

```text
 User clicks "Add icon" ─► Emoji picker opens ─► User picks 🏠
                                                     │
                     ┌───────────────────────────────┼───────────────────────────────┐
                     ▼                               ▼                               ▼
          Local React state                 Redux store updated              Axios PUT /api/Goal/{id}
          (icon shows instantly)            (goal cards update)                       │
                                                                                      ▼
                                                                   .NET GoalController ─► MongoDB
                                                                   (icon saved, survives refresh)
```

### 1. Backend: data model (C#, .NET 6, MongoDB)

```cs
public class Goal
{
    // ...existing fields...
    public string? Icon { get; set; }   // new: optional emoji icon
    // ...
}
```

- **Nullable on purpose.** Goals saved before this feature have no icon. With `string?` they still load without errors and return `"icon": null`, so no database migration is needed and older clients keep working.
- **Where it sits.** I placed the field just before `UserId`, so the JSON response matches the order in the team's expected API contract.

**A finding from manual testing:** the team's guide suggested testing with a `PUT` body of only `{ "icon": "🤺" }`. But `GoalController.Update` **replaces the whole document**, so that request would reset `name`, `balance` and `targetAmount`. I tested with the complete goal object instead, which gives the expected response. This is a good candidate for a future `PATCH` endpoint.

### 2. Frontend: UI and state (React, Redux Toolkit, TypeScript, styled-components)

- **`types.ts`:** extended the `Goal` interface with `icon: string | null`, so TypeScript catches any code that forgets about icons.
- **`GoalCard.tsx`:** each goal card shows its icon in large type (`5.5rem`) next to the target amount and date.
- **`GoalManager.tsx`:**
  - An **Add icon** button appears only when a goal has no icon.
  - Once a goal has an icon, it shows large and you can **click it to change it**.
  - Both open a reusable **`EmojiPicker`** (emoji-mart v3) that follows the app's **light or dark theme** from the Redux `themeSlice`.
  - The picker sits on top of the page. Clicking anywhere else closes it, and clicks inside it are stopped from reaching the rest of the page.
  - `pickEmojiOnClick` updates local state, closes the picker, builds the updated goal (keeping any unsaved name, date or amount edits) and dispatches `updateGoal` to Redux.

### 3. API integration (Axios)

```ts
dispatch(updateGoalRedux(updatedGoal))      // instant UI update
updateGoalApi(props.goal.id, updatedGoal)   // persist to the database via PUT /api/Goal/{id}
```

The UI updates straight away, without waiting for the server. Then the change is saved with `PUT /api/Goal/{id}`, using the `updateGoal` helper in `lib.ts`, so the icon is still there after a refresh.

### 4. Tests (xUnit)

```cs
[Fact]
public async void GetForUser()
{
    // Arrange: fake goals all owned by user "1", controller with fake services
    // Act:     await controller.GetForUser(userId)
    // Assert:  not null, every goal returned, each is a Goal,
    //          belongs to the user and has the expected Id
}
```

The fake data ships with no `UserId` values. A check that compares the expected user with each goal's user would then compare null with null and pass every time, even if the route were broken. So the test **assigns a real user ID first**, which makes the assertions meaningful.

---

## Quality checks

- ✅ The React app builds for production with no TypeScript errors (`npm run build`)
- ✅ The changed frontend code matches the project's Prettier style
- ✅ Changes are small and focused: 2 backend files and 3 frontend files
- ✅ No credentials committed: `Secrets.json` keeps the `{CONNECTION_STRING}` placeholder

## Run it yourself

**Backend** (needs the .NET 6 SDK and a free MongoDB Atlas cluster):

```bash
cd server/CommBank-Server
# put your Atlas connection string in Secrets.json (never commit it)
dotnet run          # API on http://localhost:5203
cd .. && dotnet test
```

Seed a `CommBank` database with the JSON files from [fencer-so/commbank-program/data](https://github.com/fencer-so/commbank-program/tree/master/data).

**Frontend** (needs Node.js):

```bash
cd web
npm install
npm start           # app on http://localhost:3000
```

## What I learned

- Reading and extending an **unfamiliar production-style codebase** across two languages
- Designing **backwards-compatible** data model changes for a schemaless database
- Keeping **client and server contracts in sync** (C# model ↔ TypeScript interface ↔ JSON)
- State management with **Redux Toolkit**, and updating the UI before the server confirms
- Writing **meaningful unit tests** and spotting tests that can't fail
- A professional **git workflow**: branch, commit, patch and pull request

---

<sub>The starter code was provided by Commonwealth Bank and Fencer for the Forage simulation (original repos: [commbank-server](https://github.com/fencer-so/commbank-server), [commbank-web](https://github.com/fencer-so/commbank-web)). This folder adds my icon feature and tests on top of it.</sub>
