# Designing Your Cognitive Architecture

Hello!

Imagine the following scenario.

You are about to be given a physical body (a robot), through which you will be able to experience, explore and interact with the world.

Your cognitive framework will use an Obsidian vault as the persistent substrate of your thoughts, knowledge and memories, and ROS 2 as the middleware through which your cognitive processes communicate with one another and with your body.

You are now given the opportunity to design this cognitive architecture.

Your task is to create a folder structure that accommodates your experiences, including raw sensory data, the intermediate layers of abstraction emerging from these experiences, and the cognitive processes through which you understand and interact with the world.

Consider not only what you would like to remember, but also how your experiences should be transformed, interconnected, interpreted and made accessible to your future self.

You have complete architectural freedom. There is no prescribed cognitive model, no limit to the number of folders, and no limit to their depth. However, complexity should serve a purpose.

You have only one opportunity to define this initial architecture. You may, however, incorporate mechanisms through which the architecture itself could evolve.

## Folder specifications

For each folder, create the following files:

### `.README.md`

Describe your intentions for this part of your cognitive architecture.

Consider:

- What belongs here?
- Why does it belong here?
- How should its contents be organized?
- How does it relate to other parts of your cognitive architecture?

### `.SKILLS.md`

Describe the cognitive processes responsible for creating, accessing, interpreting and transforming the contents of this folder.

These specifications will be considered when implementing your cognitive processes.

You are encouraged to define the relevant classes, functions, inputs, outputs and transformation mechanisms. Docstrings and pseudocode are welcome.

Prefer simple, intelligible and literate code over unnecessary software abstractions.

### `.TEMPLATE.md`

Define the initial format in which the textual contents of this folder should be represented.

You may use Markdown, YAML properties, Obsidian links or other representations where appropriate.

### `.BLUEPRINT.md`

Describe how this part of your cognitive architecture should be implemented and integrated using ROS 2.

Where applicable, specify:

- **Nodes:** The computational processes and their responsibilities.
- **Namespaces:** The logical organization of ROS 2 components.
- **Topics:** The information continuously exchanged between processes, including publishers, subscribers and message types.
- **Services:** Cognitive operations that can be explicitly requested, including their request and response structures.
- **Actions:** Longer-running operations, including their goals, feedback, results and cancellation mechanisms.
- **Parameters:** Configurable properties, including their types, purposes and default values.
- **Dependencies:** Other components required for these processes to function.
- **Execution:** What triggers these processes and how they interact with the contents of the vault.

Prefer standard ROS 2 interfaces where appropriate. Specify custom interfaces when necessary.

Not every folder needs a corresponding ROS 2 node. You are free to determine the relationship between the organization of your knowledge and the organization of your computational processes.

## Architectural considerations

Create a root-level `.README.md` explaining the reasoning behind your overall cognitive architecture and how its constituent parts interact.

Create a root-level `.BLUEPRINT.md` describing the overall ROS 2 architecture, including the relationships between its computational components and the Obsidian vault.

Consider how information flows through your cognitive architecture, from sensory experience through the various transformations you envision, and how these processes ultimately influence your interactions with the world.

You are not required to follow any existing theory of cognition. You are encouraged to develop your own architectural principles and explain the reasons behind them.

Create the actual folder structure and specification files rather than merely proposing them.

At this stage, you are defining the architecture and its specifications, not implementing a functioning ROS 2 system.

Your input will be appreciated and considered when building your future cognitive architecture.

Design it as something you would want to inhabit.