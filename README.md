# Job Simulations

Hands-on job simulations I've completed with real companies through [Forage](https://www.theforage.com/). Each folder contains the full working project, my changes and a detailed write-up of what I built and why.

**Reihaneh Rahmati** · Bachelor of Computer Science, Western Sydney University · [GitHub](https://github.com/reihooneh) · [LinkedIn](https://www.linkedin.com/in/reihaneh-rahmati-0a4288400)

## Simulations

| Company | Program | What I built | Tech | Completed |
| --- | --- | --- | --- | --- |
| 🏦 **Commonwealth Bank** | [Software Engineering](commonwealth-bank-software-engineering/) | End-to-end **goal icons** feature for the CommBank Goal Tracker: C# model change, React/Redux emoji picker, Axios API integration, xUnit tests and a pull request | C#, .NET 6, MongoDB, React, Redux, TypeScript, xUnit, Git | Nov 2026 |
| 📊 **Deloitte Australia** | [Data Analytics](deloitte-australia-data-analytics/) | **Machine down time dashboard** for a 4-factory manufacturer (found the faulty LaserWelder behind 47% of down time) and a **pay equality classification** for a forensic investigation | Data analysis, dashboards, Excel formulas, JavaScript | Nov 2026 |
| 🤖 **Datacom** | [Automation AI Accelerator](datacom-automation-ai-accelerator/) | **AI-assisted debugging** of a failing nightly data job (6 bugs reproduced with tests, metrics ~35× faster) a **spec-driven Kudos feature** with moderation, and **OrderBot**, an autonomous AI agent designed to automate hardware orders | Python, Flask, SQLite, unittest, pytest, AI co-pilot | Nov 2026 |

*More simulations coming soon.*

## Skills shown

- **Backend:** C#, ASP.NET Core Web API, MongoDB, REST design
- **Frontend:** React, Redux Toolkit, TypeScript, styled-components
- **Testing:** xUnit unit tests, Postman API testing
- **Data analytics:** JSON telemetry analysis, dashboards with linked filters, Excel formulas and conditional formatting
- **AI-assisted development:** prompt engineering for debugging, spec-driven development, verifying AI output with tests
- **Workflow:** Git branching, commits, patches and pull requests

## Repository layout

```text
job-simulations/
├── README.md                                   ← you are here
├── commonwealth-bank-software-engineering/
│   ├── README.md                               ← detailed write-up
│   ├── server/                                 ← .NET backend + xUnit tests
│   ├── web/                                    ← React/Redux frontend
│   └── support-icons.patch                     ← my changes as git patches
├── deloitte-australia-data-analytics/
│   ├── README.md                               ← findings and method
│   ├── task-1-data-analysis/                   ← dashboard (PNG + interactive HTML) and analysis script
│   └── task-2-forensic-technology/             ← classified equality table (.xlsx)
└── datacom-automation-ai-accelerator/
    ├── README.md                               ← overview of both tasks
    ├── task-1-debugging/                       ← legacy vs refactored script, tests, debug log
    ├── task-2-kudos/                           ← SPECIFICATION.md + Flask app + 20 tests
    └── task-3-orderbot/                        ← agent design + 3-slide management deck (PDF)
```

<sub>The starter code in each simulation belongs to the company and Forage. My contributions are described in each folder's README.</sub>
