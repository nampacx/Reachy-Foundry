param location string
param tags object = {}
param accountName string
param projectName string

@description('Model deployments to create on the Foundry resource.')
param deployments array

@description('Principals ({ id, type: User|ServicePrincipal }) granted the Foundry User role (Azure AI User).')
param foundryUserPrincipals array = []

// Azure AI User ("Foundry User"): run agents / call models with Entra ID.
var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

// One Foundry resource (AIServices) hosts the project, the model deployments and Azure Speech (STT/TTS).
resource account 'Microsoft.CognitiveServices/accounts@2026-03-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    // The Speech REST calls from the robot use the resource key; model/agent calls use Entra ID.
    disableLocalAuth: false
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-03-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Reachy Mini'
    description: 'Project for the Reachy Mini voice agent.'
  }
}

// Deployments must be created one at a time on an account.
@batchSize(1)
resource modelDeployments 'Microsoft.CognitiveServices/accounts/deployments@2026-03-01' = [
  for d in deployments: {
    parent: account
    name: d.name
    sku: {
      name: d.skuName
      capacity: d.capacity
    }
    properties: {
      model: {
        format: 'OpenAI'
        name: d.modelName
        version: d.modelVersion
      }
      versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
    }
    dependsOn: [project]
  }
]

resource foundryUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for p in foundryUserPrincipals: {
    scope: account
    name: guid(account.id, p.id, foundryUserRoleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
      principalId: p.id
      principalType: p.type
    }
  }
]

output accountName string = account.name
output projectName string = project.name
output projectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
output speechEndpoint string = 'https://${account.name}.cognitiveservices.azure.com'
